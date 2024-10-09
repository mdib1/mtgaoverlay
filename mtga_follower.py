"""
Follows along a Magic Arena log, parses the messages, and passes along
the parsed data to an API endpoint.

Licensed under GNU GPL v3.0 (see included LICENSE).

This MTGA log follower is unofficial Fan Content permitted under the Fan
Content Policy. Not approved/endorsed by Wizards. Portions of the
materials used are property of Wizards of the Coast. (C) Wizards of the
Coast LLC. See https://company.wizards.com/fancontentpolicy for more
details.
"""
from pynput import mouse
import argparse
import copy
import json
import getpass
import itertools
import os
import os.path
import pathlib
import re
import subprocess
import sys
import time
import datetime
import traceback
import uuid
import threading

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QThread, pyqtSignal


from carddata import *
from card_positions import *

from collections import defaultdict
from collections import Counter


import threading
from overlay import *

import dateutil.parser

import seventeenlands.api_client
import api_client
import seventeenlands.logging_utils

logger = seventeenlands.logging_utils.get_logger('17Lands')

CLIENT_VERSION = '0.1.42.p'

UPDATE_CHECK_INTERVAL = datetime.timedelta(hours=1)
UPDATE_PROMPT_FREQUENCY = 24

TOKEN_ENTRY_TITLE = 'MTGA Log Client Token'
TOKEN_ENTRY_MESSAGE = 'Please enter your client token from 17lands.com/account: '
TOKEN_MISSING_TITLE = 'Error: Client Token Needed'
TOKEN_MISSING_MESSAGE = 'Error: The program cannot continue without specifying a client token. Exiting.'
TOKEN_INVALID_MESSAGE = 'That token is invalid. Please specify a valid client token. See 17lands.com/getting_started for more details.'

FILE_UPDATED_FORCE_REFRESH_SECONDS = 60

OSX_LOG_ROOT = os.path.join('Library','Logs')
WINDOWS_LOG_ROOT = os.path.join(
    'users',
    getpass.getuser(),
    'AppData',
    'LocalLow',
)
STEAM_LOG_ROOT = os.path.join(
    'steamapps',
    'compatdata',
    '2141910',
    'pfx',
    'drive_c',
    'users',
    'steamuser',
    'AppData',
    'LocalLow',
)
LOG_INTERMEDIATE = os.path.join('Wizards Of The Coast', 'MTGA')
CURRENT_LOG = 'Player.log'
PREVIOUS_LOG = 'Player-prev.log'
CURRENT_LOG_PATH = os.path.join(LOG_INTERMEDIATE, CURRENT_LOG)
PREVIOUS_LOG_PATH = os.path.join(LOG_INTERMEDIATE, PREVIOUS_LOG)

POSSIBLE_ROOTS = (
    # OSX
    os.path.join(os.path.expanduser('~'), OSX_LOG_ROOT),

    # Steam
    os.path.join(
        os.path.expanduser('~'),
        '.steam',
        'steam',
        STEAM_LOG_ROOT,
    ),
    os.path.join(
        os.path.expanduser('~'),
        '.local',
        'share',
        'Steam',
        STEAM_LOG_ROOT,
    ),

    # Windows
    os.path.join('C:/', WINDOWS_LOG_ROOT),
    os.path.join('D:/', WINDOWS_LOG_ROOT),

    # Lutris
    os.path.join(
        os.path.expanduser('~'),
        'Games',
        'magic-the-gathering-arena',
        'drive_c',
        WINDOWS_LOG_ROOT,
    ),

    # Wine
    os.path.join(
        os.environ.get(
            'WINEPREFIX',
            os.path.join(os.path.expanduser('~'), '.wine'),
        ),
        'drive_c',
        WINDOWS_LOG_ROOT,
    ),
)

POSSIBLE_CURRENT_FILEPATHS = list(map(lambda root_and_path: os.path.join(*root_and_path), itertools.product(POSSIBLE_ROOTS, (CURRENT_LOG_PATH, ))))
POSSIBLE_PREVIOUS_FILEPATHS = list(map(lambda root_and_path: os.path.join(*root_and_path), itertools.product(POSSIBLE_ROOTS, (PREVIOUS_LOG_PATH, ))))

CONFIG_FILE = os.path.join(os.path.expanduser('~'), '.mtga_follower.ini')

LOG_START_REGEX_TIMED = re.compile(r'^\[(UnityCrossThreadLogger|Client GRE)\](\d[\d:/ .-]+(AM|PM)?)')
LOG_START_REGEX_UNTIMED = re.compile(r'^\[(UnityCrossThreadLogger|Client GRE)\]')
TIMESTAMP_REGEX = re.compile('^([\\d/.-]+[ T][\\d]+:[\\d]+:[\\d]+( AM| PM)?)')
STRIPPED_TIMESTAMP_REGEX = re.compile('^(.*?)[: /]*$')
JSON_START_REGEX = re.compile(r'[\[\{]')
ACCOUNT_INFO_REGEX = re.compile(r'.*Updated account\. DisplayName:(.*), AccountID:(.*), Token:.*')
MATCH_ACCOUNT_INFO_REGEX = re.compile(r'.*: ((\w+) to Match|Match to (\w+)):')
SLEEP_TIME = 0.5

TIME_FORMATS = (
    '%Y-%m-%d %I:%M:%S %p',
    '%Y-%m-%d %H:%M:%S',
    '%m/%d/%Y %I:%M:%S %p',
    '%m/%d/%Y %H:%M:%S',
    '%Y/%m/%d %I:%M:%S %p',
    '%Y/%m/%d %H:%M:%S',
    '%Y/%m/%d %I:%M:%S %p',
    '%d/%m/%Y %H:%M:%S',
    '%d/%m/%Y %I:%M:%S %p',
    '%d.%m.%Y %H:%M:%S',
    '%d.%m.%Y %I:%M:%S %p'
)
OUTPUT_TIME_FORMAT = '%Y%m%d%H%M%S'
MAX_MILLISECONDS_SINCE_EPOCH = int(1000 * datetime.datetime(3000, 1, 1).timestamp())

_ERROR_LINES_RECENCY = 10

def list_difference(list1, list2):
    count1 = Counter(list1)
    count2 = Counter(list2)
    return [item for item in list1 if count1[item] > count2[item]]

import json


def is_point_inside_polygon(x, y, polygon):
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def get_card_packdebug_info(card_id, cards_in_set_df):
    try:
        # Lookup card in cards_in_set_df by card_id
        card_row = cards_in_set_df[cards_in_set_df['id'] == card_id]
        
        if card_row.empty:
            return json.dumps({"error": f"Card ID {card_id} not found"})
        
        # Extract the card information
        name = card_row['name'].values[0]
        rarity = card_row['rarity'].values[0] if 'rarity' in card_row.columns else None
        number = card_row['number'].values[0] if 'number' in card_row.columns else None
        boosterTypes = card_row['boosterTypes'].values[0] if 'boosterTypes' in card_row.columns else None
        
        # Create a dictionary with the card information
        card_info = {
            'id': card_id,
            'name': name,
            'rarity': rarity,
            'number': number,
            'boosterTypes': boosterTypes
        }
        
        # Remove any None values to keep the JSON clean
        card_info = {k: v for k, v in card_info.items() if v is not None}

        return card_info
    
    except Exception as e:
        logger.error(f'Error processing get_card_packdebug_info: {e}')
        return json.dumps({"error": f"Error processing card ID {card_id}: {str(e)}"})

def get_card_info(card_id, cards_in_set_df):
    try:
        # Lookup card in cards_in_set_df by card_id
        card_row = cards_in_set_df[cards_in_set_df['id'] == card_id]
        # If card exists, extract the details
        if not card_row.empty:
            card_name = card_row['name'].values[0]
            
            # Check if each column exists and get its value, or use 'N/A' if it doesn't exist
            GDWR = card_row['GDWR'].values[0] if 'GDWR' in card_row.columns else 'N/A'
            OHWR = card_row['OHWR'].values[0] if 'OHWR' in card_row.columns else 'N/A'
            GIHWR = card_row['GIHWR'].values[0] if 'GIHWR' in card_row.columns else 'N/A'
            
            # Format the string based on which values are available
            info_parts = []
            info_parts.append(f"GDWR: {GDWR:.2f}" if isinstance(GDWR, float) else f"GDWR: {GDWR}")
            info_parts.append(f"OHWR: {OHWR:.2f}" if isinstance(OHWR, float) else f"OHWR: {OHWR}")
            info_parts.append(f"GIHWR: {GIHWR:.2f}" if isinstance(GIHWR, float) else f"GIHWR: {GIHWR}")            
            # if GDWR != 'N/A':
            #     info_parts.append(f"GDWR: {GDWR:.2f}" if isinstance(GDWR, float) else f"GDWR: {GDWR}")
            # if OHWR != 'N/A':
            #     info_parts.append(f"OHWR: {OHWR:.2f}" if isinstance(OHWR, float) else f"OHWR: {OHWR}")
            # if GIHWR != 'N/A':
            #     info_parts.append(f"GIHWR: {GIHWR:.2f}" if isinstance(GIHWR, float) else f"GIHWR: {GIHWR}")
            
            #info_string = ", ".join(info_parts)
            info_string = ""
            for part in info_parts:
                info_string += part
                info_string += "\n"

            #formatted_string = f"{card_name} ({info_string})" if info_parts else card_name
            formatted_string = f"{info_string}" if info_parts else card_name
            
            # Use GIHWR for sorting if it exists and is a number, otherwise use 0
            sort_value = float(GIHWR) if isinstance(GIHWR, (int, float)) else 0
            
            return (formatted_string, sort_value)
        else:
            return (f"Card ID {card_id} not found", float('-inf'))  # Assign -inf for cards not found
    except Exception as e:
        logger.error(f'Error processing get_card_info: {e}')
        return (f"Error processing card ID {card_id}", float('-inf'))

def extract_time(time_str):
    """
    Convert a time string in various formats to a datetime.

    :param time_str: The string to convert.

    :returns: The resulting datetime object.
    :raises ValueError: Raises an exception if it cannot interpret the string.
    """
    time_str = STRIPPED_TIMESTAMP_REGEX.match(time_str).group(1)
    if ': ' in time_str:
        time_str = time_str.split(': ')[0]

    for possible_format in TIME_FORMATS:
        try:
            return datetime.datetime.strptime(time_str, possible_format)
        except ValueError:
            pass
    raise ValueError(f'Unsupported time format: "{time_str}"')


def json_value_matches(expectation, path, blob):
    """
    Check if the value nested at a given path in a JSON blob matches the expected value.

    :param expectation: The value to check against.
    :param path:        A list of keys for the nested value.
    :param blob:        The JSON blob to check in.

    :returns: Whether or not the value exists at the given path and it matches expectation.
    """
    for p in path:
        if p in blob:
            blob = blob[p]
        else:
            return False
    return blob == expectation


def get_rank_string(rank_class, level, percentile, place, step):
    """
    Convert the components of rank into a serializable value for recording

    :param rank_class: Class (e.g. Bronze, Mythic)
    :param level:      Level within the class
    :param percentile: Percentile (within Mythic)
    :param place:      Leaderboard place (within Mythic)
    :param step:       Step towards next level

    :returns: Serialized rank string (e.g. "Gold-3-0.0-0-2")
    """
    return '-'.join(str(x) for x in [rank_class, level, percentile, place, step])

class Round:
    def __init__(self):
        self.boosters = []
        for x in range(14):
            self.boosters.append([])

class DraftOpens:
    def __init__(self):
        round1 = Round()
        round2 = Round()
        round3 = Round()
        self.rounds = [round1, round2, round3]        

class Follower:
    """Follows along a log, parses the messages, and passes along the parsed data to the API endpoint."""

    def __init__(self, token, follower_thread, host, debug_mode):
        self.debug_mode = debug_mode
        #self.overlay_active = False
        self.host = host
        self.token = token
        self.json_decoder = json.JSONDecoder()
        #self._api_client = seventeenlands.api_client.ApiClient(host=host)
        self._api_client = api_client.ApiClient(host=host)
        self._reinitialize()
        #self.OVERLAY_UPDATE_INTERVAL = .01
        self.OVERLAY_UPDATE_INTERVAL_MAX_TIME = 5
        self.__DOUBLE_CLICK_DELAY = 1
        self.TIME_TO_WAIT_FOR_MOUSE_BASED_OVERLAY_UPDATE = 0.3
        self.mouse_listener = mouse.Listener(on_click=self.on_click)
        self.mouse_listener.start()        
        self.click_area = [(2179, 8), (2179, 88), (2090, 88), (2090, 8)]        
        self.__last_mouse_click_time = 0        
        self.last_overlay_update = 0
        self.__last_card_positions = None        
        self.__last_pack = None        
        self.__draft_opens = DraftOpens()        
        self.__time_last_overlaid = None
        self.__cards_in_set_df = None
        self.__set_data_not_available = False        
        self.__currentScene = None
        self.__last_card_details_withstats = []
        self.__update_timer = None
        
        #self.__overlay_manager = overlay_manager
        self.follower_thread = follower_thread


    def _reinitialize(self):
        self.buffer = []
        self.cur_log_time = datetime.datetime.fromtimestamp(0)
        self.last_utc_time = datetime.datetime.fromtimestamp(0)
        self.last_raw_time = ''
        self.disconnected_user = None
        self.disconnected_screen_name = None
        self.disconnected_rank = None
        self.cur_user = None
        self.cur_draft_event = None
        self.cur_rank_data = None
        self.cur_opponent_level = None
        self.cur_opponent_match_id = None
        self.current_match_id = None
        self.current_event_id = None
        self.starting_team_id = None
        self.seat_id = None
        self.turn_count = 0
        self.current_game_maindeck = None
        self.current_game_sideboard = None
        self.game_service_metadata = None
        self.game_client_metadata = None
        self.objects_by_owner = defaultdict(dict)
        self.opening_hand_count_by_seat = defaultdict(int)
        self.opening_hand = defaultdict(list)
        self.drawn_hands = defaultdict(list)
        self.drawn_cards_by_instance_id = defaultdict(dict)
        self.cards_in_hand = defaultdict(list)
        self.user_screen_name = None
        self.screen_names = defaultdict(lambda: '')
        self.game_history_events = []
        self.pending_game_submission = {}
        self.pending_game_result = {}
        self.pending_match_result = {}

        self.last_blob = ''
        self.current_debug_blob = ''
        self.recent_lines = []

        self.__last_mouse_click_time = 0        
        self.last_overlay_update = 0
        self.__last_card_positions = None        
        self.__last_pack = None        
        self.__draft_opens = DraftOpens()        
        self.__time_last_overlaid = None
        self.__cards_in_set_df = None
        self.__set_data_not_available = False        
        self.__currentScene = None        
        self.__last_card_details_withstats = []

        self.__clear_match_data()

    def on_click(self, x, y, button, pressed):
        if pressed:
            if is_point_inside_polygon(x, y, self.click_area):
                #logger.info(f"Click detected inside the specified area at ({x}, {y})")
                # Perform action for click inside the area
                TIME_SINCE_LAST_MOUSE_CLICK = time.time() - self.__last_mouse_click_time
                if TIME_SINCE_LAST_MOUSE_CLICK > self.__DOUBLE_CLICK_DELAY:
                    logger.info("Updating due to mouse click")
                    self.__last_mouse_click_time = time.time()

                    if self.__update_timer:
                        self.__update_timer.cancel()

                    self.__update_timer = threading.Timer(self.TIME_TO_WAIT_FOR_MOUSE_BASED_OVERLAY_UPDATE, self.__update_overlays)
                    self.last_overlay_update = time.time()
                    self.__update_timer.start()
                                                                
                    #self.__update_overlays()
            #else:
                #logger.info(f"Click detected outside the specified area at ({x}, {y})")
                # Optionally, perform a different action or do nothing

    def _add_base_api_data(self, blob):
        return {
            "token": self.token,
            "client_version": CLIENT_VERSION,
            "player_id": self.cur_user,
            "time": self.cur_log_time.isoformat(),
            "utc_time": self.last_utc_time.isoformat(),
            "raw_time": self.last_raw_time,
            **blob,
        }

    def parse_log(self, filename, follow):
        """
        Parse messages from a log file and pass the data along to the API endpoint.

        :param filename: The filename for the log file to parse.
        :param follow:   Whether or not to continue looking for updates to the file after parsing
                         all the initial lines.
        """
        while True:
            self._reinitialize()
            last_read_time = time.time()
            last_file_size = 0
            try:
                with open(filename, errors='replace') as f:
                    while True:                       
                        line = f.readline()
                        file_size = pathlib.Path(filename).stat().st_size
                        if line:
                            self.__append_line(line)
                            last_read_time = time.time()
                            last_file_size = file_size
                        else:
                            self.__handle_complete_log_entry()
                            last_modified_time = os.stat(filename).st_mtime
                            if file_size < last_file_size:
                                logger.info(f'Starting from beginning of file as file is smaller than before (previous = {last_file_size}; current = {file_size})')
                                break
                            elif last_modified_time > last_read_time + FILE_UPDATED_FORCE_REFRESH_SECONDS:
                                logger.info(f'Starting from beginning of file as file has been updated much more recently than the last read (previous = {last_read_time}; current = {last_modified_time})')
                                break
                            elif follow:
                                OVERLAY_UPDATE_INTERVAL_MAX_TIME_ELAPSED = time.time() - self.last_overlay_update >= self.OVERLAY_UPDATE_INTERVAL_MAX_TIME
                                #logger.info(str(current_time - self.last_overlay_update)+" seconds since last update")
                                if OVERLAY_UPDATE_INTERVAL_MAX_TIME_ELAPSED:
                                    self.last_overlay_update = time.time()
                                    logger.info("updating due to time elapsing")
                                    self.__update_overlays()
                                time.sleep(SLEEP_TIME)
                            else:
                                break
            except FileNotFoundError:
                time.sleep(SLEEP_TIME)
            except Exception as e:
                self._log_error(
                    message=f'Error parsing log: {e}',
                    error=e,
                    stacktrace=traceback.format_exc(),
                )
                break

            if not follow:
                logger.info('Done processing file.')
                break

    def _log_error(self, message: str, error: Exception, stacktrace: str):
        logger.error(message)
        #self._api_client.submit_error_info(self._add_base_api_data({
        #    "blob": self.current_debug_blob,
        #    "recent_lines": self.recent_lines,
        #    "stacktrace": traceback.format_exc(),
        #}))

    def __check_detailed_logs(self, line):
        if (line.startswith('DETAILED LOGS: DISABLED')):
            logger.warning('Detailed logs are disabled in MTGA.')
            show_message(
                title='MTGA Logging Disabled (17Lands)',
                message=(
                    '17Lands needs detailed logging enabled in MTGA. To enable this, click the '
                    'gear at the top right of MTGA, then "View Account" (at the bottom), then '
                    'check "Detailed Logs", then restart MTGA.'
                ),
            )
        elif (line.startswith('DETAILED LOGS: ENABLED')):
            logger.info('Detailed logs enabled in MTGA.')

    def __append_line(self, line):
        """Add a complete line (not necessarily a complete message) from the log."""
        if len(self.recent_lines) >= _ERROR_LINES_RECENCY:
            self.recent_lines.pop(0)
        self.recent_lines.append(line)

        self.__check_detailed_logs(line)

        self.__maybe_handle_account_info(line)

        timestamp_match = TIMESTAMP_REGEX.match(line)
        if timestamp_match:
            self.last_raw_time = timestamp_match.group(1)
            self.cur_log_time = extract_time(self.last_raw_time)

        match = LOG_START_REGEX_UNTIMED.match(line)
        if match:
            self.__handle_complete_log_entry()

            timed_match = LOG_START_REGEX_TIMED.match(line)
            if timed_match:
                self.last_raw_time = timed_match.group(2)
                self.cur_log_time = extract_time(self.last_raw_time)
                self.buffer.append(line[timed_match.end():])
            else:
                self.buffer.append(line[match.end():])
        else:
            self.buffer.append(line)

    def __handle_complete_log_entry(self):
        """Mark the current log message complete. Should be called when waiting for more log messages."""   
        if len(self.buffer) == 0:
            return
        if self.cur_log_time is None:
            self.buffer = []
            return

        full_log = ''.join(self.buffer)
        self.current_debug_blob = full_log
        if full_log != self.last_blob:
            try:
                self.__handle_blob(full_log)
            except Exception as e:
                self._log_error(
                    message=f'Error {e} while processing {full_log}',
                    error=e,
                    stacktrace=traceback.format_exc(),
                )

            self.last_blob = full_log
        else:
            logger.info(f'Skipping repeated complete log entry: {full_log}')

        self.buffer = []
        #self.cur_log_time = None

    def __maybe_get_utc_timestamp(self, blob):
        timestamp = None
        if 'timestamp' in blob:
            timestamp = blob['timestamp']
        elif 'timestamp' in blob.get('payloadObject', {}):
            timestamp = blob['payloadObject']['timestamp']
        elif 'timestamp' in blob.get('params', {}).get('payloadObject', {}):
            timestamp = blob['params']['payloadObject']['timestamp']

        if timestamp is None:
            return None

        try:
            timestamp_value = int(timestamp)

            if timestamp_value < MAX_MILLISECONDS_SINCE_EPOCH:
                return datetime.datetime.fromtimestamp(timestamp_value * 0.001)

            else:
                seconds_since_year_1 = timestamp_value / 10000000
                return datetime.datetime.fromordinal(1) + datetime.timedelta(seconds=seconds_since_year_1)

        except ValueError:
            return dateutil.parser.isoparse(timestamp)

    def __handle_blob(self, full_log):
        """Attempt to parse a complete log message and send the data if relevant."""
        match = JSON_START_REGEX.search(full_log)
        #logger.info(full_log)
        if not match:
            return

        try:
            json_obj, end = self.json_decoder.raw_decode(full_log, match.start())
        except json.JSONDecodeError as e:
            logger.debug(f'Ran into error {e} when parsing at {self.cur_log_time}. Data was: {full_log}')
            return

        json_obj = self.__extract_payload(json_obj)
        if type(json_obj) != dict: return

        maybe_time = None
        try:
            maybe_time = self.__maybe_get_utc_timestamp(json_obj)
            if maybe_time is not None:
                self.last_utc_time = maybe_time
                
                #Ensure maybe_time is timezone-aware
                if maybe_time.tzinfo is None:
                    maybe_time = maybe_time.replace(tzinfo=datetime.timezone.utc)
                
                current_time = datetime.datetime.now(datetime.timezone.utc)
                time_difference = (current_time - maybe_time).total_seconds()
                
                #logger.info(f'Log entry timestamp: {maybe_time}')
                #logger.info(f'Current time: {current_time}')
                #logger.info(f'Time difference: {time_difference} seconds')
                
                if time_difference > 10:
                    logger.info(f'Skipping old log entry from {maybe_time}')
                    return
                else:
                    logger.info(f'Processing log entry from {maybe_time}')
        except Exception as e:
            logger.error(f'Error processing timestamp: {e}')
            logger.error(f'maybe_time: {maybe_time}, type: {type(maybe_time)}')
            logger.error(f'current_time: {current_time}, type: {type(current_time)}')
            return


        if json_value_matches('Client.Connected', ['params', 'messageName'], json_obj): # Doesn't exist any more
            self.__handle_login(json_obj)
        elif 'SceneChange' in full_log and 'fromSceneName' in json_obj:
            self.__handle_scenechange(json_obj)
        elif 'Event_Join' in full_log and 'EventName' in json_obj:
            self.__handle_joined_pod(json_obj)
        elif 'DraftStatus' in json_obj:
            self.__handle_bot_draft_pack(json_obj)
        elif 'BotDraft_DraftPick' in full_log and 'PickInfo' in json_obj:
            self.__handle_bot_draft_pick(json_obj['PickInfo'])
        elif 'LogBusinessEvents' in full_log and 'PickGrpId' in json_obj:
            self.__handle_human_draft_combined(json_obj)
        elif 'LogBusinessEvents' in full_log and 'WinningType' in json_obj:
            self.__handle_log_business_game_end(json_obj)
        elif 'Draft.Notify ' in full_log and 'method' not in json_obj:
            self.__handle_human_draft_pack(json_obj)
        elif 'Event_SetDeck' in full_log and 'EventName' in json_obj:
            self.__handle_deck_submission(json_obj)
        elif 'Event_GetCourses' in full_log and 'Courses' in json_obj:
            self.__handle_ongoing_events(json_obj)
        elif 'Event_ClaimPrize' in full_log and 'EventName' in json_obj:
            self.__handle_claim_prize(json_obj)
        elif 'Draft_CompleteDraft' in full_log and 'DraftId' in json_obj:
            self.__handle_event_course(json_obj)
        elif 'authenticateResponse' in json_obj:
            self.__update_screen_name(json_obj['authenticateResponse']['screenName'])
        elif 'matchGameRoomStateChangedEvent' in json_obj:
            self.__handle_match_state_changed(json_obj)
        elif 'greToClientEvent' in json_obj and 'greToClientMessages' in json_obj['greToClientEvent']:
            try:
                for message in json_obj['greToClientEvent']['greToClientMessages']:
                    self.__handle_gre_to_client_message(message, maybe_time)
            except Exception as e:
                self._log_error(
                    message=f'Error {e} parsing GRE to client messages from {json_obj}',
                    error=e,
                    stacktrace=traceback.format_exc(),
                )
        elif json_value_matches('ClientToMatchServiceMessageType_ClientToGREMessage', ['clientToMatchServiceMessageType'], json_obj):
            self.__handle_client_to_gre_message(json_obj.get('payload', {}), maybe_time)
        elif json_value_matches('ClientToMatchServiceMessageType_ClientToGREUIMessage', ['clientToMatchServiceMessageType'], json_obj):
            self.__handle_client_to_gre_ui_message(json_obj.get('payload', {}), maybe_time)
        elif 'Rank_GetCombinedRankInfo' in full_log and 'limitedSeasonOrdinal' in json_obj:
            self.__handle_self_rank_info(json_obj)
        elif ' PlayerInventory.GetPlayerCardsV3 ' in full_log and 'method' not in json_obj: # Doesn't exist any more
            self.__handle_collection(json_obj)
        elif 'DTO_InventoryInfo' in json_obj:
            self.__handle_inventory(json_obj['DTO_InventoryInfo'])
        elif 'NodeStates' in json_obj and 'RewardTierUpgrade' in json_obj['NodeStates']:
            self.__handle_player_progress(json_obj)
        elif 'FrontDoorConnection.Close ' in full_log:
            self.__reset_current_user()
        elif 'Reconnect result : Connected' in full_log:
            self.__handle_reconnect_result()

    def __try_decode(self, blob, key):
        try:
            json_obj, _ = self.json_decoder.raw_decode(blob[key])
            return json_obj
        except Exception:
            return blob[key]

    def __extract_payload(self, blob):
        if type(blob) != dict: return blob
        if 'clientToMatchServiceMessageType' in blob: return blob

        for key in ('payload', 'Payload', 'request'):
            if key in blob:
                # Some messages are recursively serialized
                return self.__extract_payload(self.__try_decode(blob, key))

        return blob

    def __update_screen_name(self, screen_name):
        try:
            if self.user_screen_name == screen_name:
                return

            self.user_screen_name = screen_name
            user_info = {
                'player_id': self.cur_user,
                'screen_name': self.user_screen_name,
            }
            logger.info(f'Updating user info: {user_info}')
            self._api_client.submit_user(self._add_base_api_data(user_info))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing screen name from {screen_name}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_match_state_changed(self, blob):
        game_room_info = blob.get('matchGameRoomStateChangedEvent', {}).get('gameRoomInfo', {})
        game_room_config = game_room_info.get('gameRoomConfig', {})

        updated_match_id = game_room_config.get('matchId')
        updated_event_id = game_room_config.get('eventId')

        if 'reservedPlayers' in game_room_config:
            oppo_player_id = ''
            for player in game_room_config['reservedPlayers']:
                self.screen_names[player['systemSeatId']] = player['playerName'].split('#')[0]
                # Backfill the current user's screen name when possible
                if player['userId'] == self.cur_user:
                    self.__update_screen_name(player['playerName'])
                    updated_event_id = player.get('eventId', updated_event_id)
                else:
                    oppo_player_id = player['userId']

            if oppo_player_id and 'clientMetadata' in game_room_config:
                metadata = game_room_config['clientMetadata']
                self.cur_opponent_level = get_rank_string(
                    rank_class=metadata.get(f'{oppo_player_id}_RankClass'),
                    level=metadata.get(f'{oppo_player_id}_RankTier'),
                    percentile=metadata.get(f'{oppo_player_id}_LeaderboardPercentile'),
                    place=metadata.get(f'{oppo_player_id}_LeaderboardPlacement'),
                    step=None,
                )
                self.cur_opponent_match_id = game_room_config.get('matchId')
                logger.info(f'Parsed opponent rank info as limited {self.cur_opponent_level} in match {self.cur_opponent_match_id}')

        if updated_match_id and updated_event_id:
            self.current_match_id = updated_match_id
            self.current_event_id = updated_event_id

        if 'serviceMetadata' in game_room_config:
            self.game_service_metadata = game_room_config['serviceMetadata']

        if 'clientMetadata' in game_room_config:
            self.game_client_metadata = game_room_config['clientMetadata']

        if 'finalMatchResult' in game_room_info:
            results = game_room_info['finalMatchResult'].get('resultList', [])
            if results:
                if self.__enqueue_game_data():
                    self.__enqueue_game_results(results)
            self.__clear_match_data(submit_pending_game=True)

    def _add_to_game_history(self, message_blob, timestamp):
        self.game_history_events.append({
            "_timestamp": None if timestamp is None else timestamp.isoformat(),
            **message_blob,
        })

    def __handle_gre_to_client_message(self, message_blob, timestamp):
        """Handle messages in the 'greToClientEvent' field."""
        # Add to game history before processing the message, since we may submit the game right away.
        if message_blob['type'] in ['GREMessageType_QueuedGameStateMessage', 'GREMessageType_GameStateMessage']:
            self._add_to_game_history(message_blob, timestamp)
        elif message_blob['type'] == 'GREMessageType_UIMessage' and 'onChat' in message_blob['uiMessage']:
            self._add_to_game_history(message_blob, timestamp)

        if message_blob['type'] == 'GREMessageType_ConnectResp':
            self.__handle_gre_connect_response(message_blob)

        elif message_blob['type'] == 'GREMessageType_EdictalMessage':
            self.__handle_gre_edictal_message(message_blob, timestamp)

        elif message_blob['type'] == 'GREMessageType_GameStateMessage':
            try:
                system_seat_ids = message_blob.get('systemSeatIds', [])
                if len(system_seat_ids) > 0:
                    self.seat_id = system_seat_ids[0]

                game_state_message = message_blob.get('gameStateMessage', {})

                if 'gameInfo' in game_state_message:
                    game_info = game_state_message['gameInfo']
                    if game_info.get('matchID', self.current_match_id) != self.current_match_id:
                        self.current_match_id = game_info['matchID']
                        self.current_event_id = None

                turn_info = game_state_message.get('turnInfo', {})
                players = game_state_message.get('players', [])

                if turn_info.get('turnNumber'):
                    self.turn_count = turn_info.get('turnNumber')
                else:
                    turns_sum = sum(p.get('turnNumber', 0) for p in players)
                    self.turn_count = max(self.turn_count, turns_sum)

                for game_object in game_state_message.get('gameObjects', []):
                    if game_object['type'] not in ('GameObjectType_Card', 'GameObjectType_SplitCard'):
                        continue
                    owner = game_object['ownerSeatId']
                    instance_id = game_object['instanceId']
                    card_id = game_object['overlayGrpId']

                    self.objects_by_owner[owner][instance_id] = card_id

                for zone in game_state_message.get('zones', []):
                    if zone['type'] == 'ZoneType_Hand':
                        owner = zone['ownerSeatId']
                        player_objects = self.objects_by_owner[owner]
                        hand_card_ids = zone.get('objectInstanceIds', [])
                        self.cards_in_hand[owner] = [player_objects.get(instance_id) for instance_id in hand_card_ids if instance_id]
                        for instance_id in hand_card_ids:
                            card_id = player_objects.get(instance_id)
                            if instance_id is not None and card_id is not None:
                                self.drawn_cards_by_instance_id[owner][instance_id] = card_id

                players_deciding_hand = {
                    (p['systemSeatNumber'], p.get('mulliganCount', 0))
                    for p in players
                    if p.get('pendingMessageType') == 'ClientMessageType_MulliganResp'
                }
                for (player_id, mulligan_count) in players_deciding_hand:
                    if self.starting_team_id is None:
                        self.starting_team_id = turn_info.get('activePlayer')
                    self.opening_hand_count_by_seat[player_id] += 1

                    if mulligan_count == len(self.drawn_hands[player_id]):
                        self.drawn_hands[player_id].append(self.cards_in_hand[player_id].copy())

                if len(self.opening_hand) == 0 and ('Phase_Beginning', 'Step_Upkeep', 1) == (turn_info.get('phase'), turn_info.get('step'), turn_info.get('turnNumber')):
                    for (owner, hand) in self.cards_in_hand.items():
                        self.opening_hand[owner] = hand.copy()

                self.__maybe_handle_game_over_stage(game_state_message)

            except Exception as e:
                self._log_error(
                    message=f'Error {e} parsing GRE message from {message_blob}',
                    error=e,
                    stacktrace=traceback.format_exc(),
                )


    def __handle_gre_connect_response(self, blob):
        try:
            deck_info = blob.get('connectResp', {}).get('deckMessage', {})
            self.current_game_maindeck = deck_info.pop('deckCards', [])
            self.current_game_sideboard = deck_info.pop('sideboardCards', [])
            self.current_game_additional_deck_info = deck_info

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing GRE connect response from {blob}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_client_to_gre_message(self, payload, timestamp):
        try:
            if payload['type'] == 'ClientMessageType_SelectNResp':
                self._add_to_game_history(payload, timestamp)

            if payload['type'] == 'ClientMessageType_SubmitDeckResp':
                try:
                    self.__clear_game_data()
                    deck_info = payload['submitDeckResp']['deck']
                    self.current_game_maindeck = deck_info.pop('deckCards', [])
                    self.current_game_sideboard = deck_info.pop('sideboardCards', [])
                    self.current_game_additional_deck_info = deck_info

                except Exception as e:
                    self._log_error(
                        message=f'Error {e} parsing GRE deck submission from {payload}',
                        error=e,
                        stacktrace=traceback.format_exc(),
                    )

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing GRE to client messages from {payload}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_client_to_gre_ui_message(self, payload, timestamp):
        try:
            if 'onChat' in payload['uiMessage']:
                self._add_to_game_history(payload, timestamp)

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing GRE to client UI messages from {payload}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_gre_edictal_message(self, payload, timestamp):
        try:
            edictMessage = payload.get('edictalMessage', {}).get('edictMessage', {})
            return self.__handle_client_to_gre_message(edictMessage, timestamp=timestamp)

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing edictal message from {payload}',
                error=e,
                stacktrace=traceback.format_exc(),
            )


    def __handle_log_business_game_end(self, payload):
        try:
            if self.starting_team_id is None:
                self.starting_team_id = payload.get('StartingTeamId')

            if self.__enqueue_game_data():
                self.pending_game_result = {
                    'game_number': payload.get('GameNumber'),
                    'won': self.seat_id == payload.get('WinningTeamId'),
                    'win_type': payload.get('WinningType'),
                    'game_end_reason': payload.get('WinningReason'),
                }
                logger.info(f'Added pending game result via LogBusinessEvents {self.pending_game_result}')

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing game end from LogBusinessEvents: {payload}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __maybe_handle_game_over_stage(self, game_state_message):
        game_info = game_state_message.get('gameInfo', {})
        if game_info.get('stage') != 'GameStage_GameOver':
            return

        results = game_info.get('results')
        if results:
            if self.__enqueue_game_data():
                self.__enqueue_game_results(results)

    def __maybe_submit_pending_game(self):
        if self.pending_game_submission and self.pending_game_result:
            full_game = {
                **self.pending_game_result,
                **self.pending_match_result,
                **self.pending_game_submission,
            }
            logger.info(f'Submitting queued game result')
            self._api_client.submit_game_result(self._add_base_api_data(full_game))
            self.pending_game_submission = {}
            self.__clear_game_data()

    def __clear_game_data(self, submit_pending_game=True):
        if submit_pending_game:
            self.__maybe_submit_pending_game()

        self.turn_count = 0
        self.objects_by_owner.clear()
        self.opening_hand_count_by_seat.clear()
        self.opening_hand.clear()
        self.drawn_hands.clear()
        self.drawn_cards_by_instance_id.clear()
        self.starting_team_id = None
        self.game_history_events.clear()
        self.current_game_maindeck = None
        self.current_game_sideboard = None
        self.current_game_additional_deck_info = None
        self.game_service_metadata = None
        self.game_client_metadata = None
        self.pending_game_result = {}
        self.pending_match_result = {}

    def __clear_match_data(self, submit_pending_game=False):
        self.screen_names.clear()
        self.current_match_id = None
        self.current_event_id = None
        self.seat_id = None
        self.__clear_game_data(submit_pending_game=submit_pending_game)

    def __maybe_handle_account_info(self, line):
        match = ACCOUNT_INFO_REGEX.match(line)
        if match:
            screen_name = match.group(1)
            self.cur_user = match.group(2)
            self.__update_screen_name(screen_name)
            return

        match = MATCH_ACCOUNT_INFO_REGEX.match(line)
        if match:
            self.cur_user = match.group(2) or match.group(3)

    def __handle_ongoing_events(self, json_obj):
        """Handle 'Event_GetCourses' messages."""
        return
        try:
            event = {
                'courses': json_obj['Courses'],
            }
            logger.info(f'Updated ongoing events')
            self._api_client.submit_ongoing_events(self._add_base_api_data(event))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing ongoing event from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_claim_prize(self, json_obj):
        """Handle 'Event_ClaimPrize' messages."""
        try:
            event = {
                'event_name': json_obj['EventName'],
            }
            logger.info(f'Event ended: {event}')
            self._api_client.submit_event_ended(self._add_base_api_data(event))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing claim prize event from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_event_course(self, json_obj):
        """Handle messages linking draft id to event name."""
        try:
            event = {
                'event_name': json_obj['InternalEventName'],
                'draft_id': json_obj['DraftId'],
                'course_id': json_obj['CourseId'],
                'card_pool': json_obj['CardPool'],
            }
            logger.info(f'Event course: {event}')
            self._api_client.submit_event_course_submission(self._add_base_api_data(event))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing partial event course from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __has_pending_game_data(self):
        return len(self.drawn_cards_by_instance_id) > 0 and len(self.game_history_events) > 5

    def __enqueue_game_results(self, results):
        try:
            game_results = [r for r in results if r.get('scope') == 'MatchScope_Game']
            if game_results:
                this_game_result = game_results[-1]
                self.pending_game_result = {
                    'game_number': max(1, len(game_results)),
                    'won': self.seat_id == this_game_result.get('winningTeamId'),
                    'win_type': this_game_result.get('result'),
                    'game_end_reason': this_game_result.get('reason'),
                }
                logger.info(f'Added pending game result {self.pending_game_result}')

            match_result = next((r for r in results if r.get('scope') == 'MatchScope_Match'), {})
            if match_result:
                self.pending_match_result = {
                    'won_match': self.seat_id == match_result.get('winningTeamId'),
                    'match_result_type': match_result.get('result'),
                    'match_end_reason': match_result.get('reason'),
                }
                logger.info(f'Added pending match result {self.pending_match_result}')

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing game result',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __enqueue_game_data(self):
        if not self.__has_pending_game_data():
            return False

        try:
            opponent_id = 2 if self.seat_id == 1 else 1
            opponent_card_ids = [c for c in self.objects_by_owner.get(opponent_id, {}).values()]

            if self.current_match_id != self.cur_opponent_match_id:
                self.cur_opponent_level = None

            game = {
                'event_name': self.current_event_id,
                'match_id': self.current_match_id,
                'on_play': self.seat_id == self.starting_team_id,
                'opening_hand': self.opening_hand[self.seat_id],
                'mulligans': self.drawn_hands[self.seat_id][:-1],
                'drawn_hands': self.drawn_hands[self.seat_id],
                'drawn_cards': list(self.drawn_cards_by_instance_id[self.seat_id].values()),
                'mulligan_count': self.opening_hand_count_by_seat[self.seat_id] - 1,
                'opponent_mulligan_count': self.opening_hand_count_by_seat[opponent_id] - 1,
                'turns': self.turn_count,
                'duration': -1,
                'opponent_card_ids': opponent_card_ids,
                'rank_data': self.cur_rank_data,
                'opponent_rank': self.cur_opponent_level,
                'maindeck_card_ids': self.current_game_maindeck,
                'sideboard_card_ids': self.current_game_sideboard,
                'additional_deck_info': self.current_game_additional_deck_info,
                'service_metadata': self.game_service_metadata,
                'client_metadata': self.game_client_metadata,
            }
            logger.info(f'Completed game: {game}')

            # Add the history to the blob after logging to avoid printing excessive logs
            logger.info(f'Adding game history ({len(self.game_history_events)} events)')
            game['history'] = {
                'seat_id': self.seat_id,
                'opponent_seat_id': opponent_id,
                'screen_name': self.screen_names[self.seat_id],
                'opponent_screen_name': self.screen_names[opponent_id],
                'events': self.game_history_events,
            }

            self.pending_game_submission = copy.deepcopy(game)
            return True

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing game data',
                error=e,
                stacktrace=traceback.format_exc(),
            )
            return False

    def __handle_login(self, json_obj):
        """Handle 'Client.Connected' messages."""
        self.__clear_game_data(submit_pending_game=False)

        try:
            self.cur_user = json_obj['params']['payloadObject']['playerId']
            screen_name = json_obj['params']['payloadObject']['screenName']
            self.__update_screen_name(screen_name)
        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing login from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_bot_draft_pack(self, json_obj):
        """Handle 'DraftStatus' messages."""
        if json_obj['DraftStatus'] == 'PickNext':
            self.__clear_game_data()
            #time.sleep(5)
            try:
                self.cur_draft_event = json_obj['EventName']
                pack = {
                    'event_name': json_obj['EventName'],
                    'pack_number': int(json_obj['PackNumber']),
                    'pick_number': int(json_obj['PickNumber']),
                    'card_ids': [int(x) for x in json_obj['DraftPack']],
                }
                #logger.info(f'Draft pack: {pack}')
                #pack_info = f"Pack {pack['pack_number']}, Pick {pack['pick_number']}\nCards: {', '.join(map(str, pack['card_ids']))}"                 
                self.__prep_and_show_overlay(pack)
                self._api_client.submit_draft_pack(self._add_base_api_data(pack))

            except Exception as e:
                self._log_error(
                    message=f'Error {e} parsing draft pack from {json_obj}',
                    error=e,
                    stacktrace=traceback.format_exc(),
                )
    def __update_draft_opens(self, pack):
        booster_num = pack['pick_number'] % 8
        pack_number_index = pack['pack_number'] - 1
        #logger.info("updating booster "+str(booster_num)        )
        if len(self.__draft_opens.rounds[pack_number_index].boosters[booster_num]) == 0:
            self.__draft_opens.rounds[pack_number_index].boosters[booster_num] = pack['card_ids']
            #logger.info ("added booster "+str(booster_num)+" with card ids "+str(pack['card_ids']))
        else:
            #logger.info("booster "+str(booster_num)+" already exists, here are the cards its missing:")
            #set1 = set(self.__draft_opens.rounds[pack_number_index].boosters[booster_num])
            #set2 = set(pack['card_ids'])
            #missing_cards = list(set1 - set2)         
            #logger.info(self.__draft_opens.rounds[pack_number_index].boosters[booster_num])   
            #logger.info(pack['card_ids'])
            missing_cards = list_difference(self.__draft_opens.rounds[pack_number_index].boosters[booster_num], pack['card_ids'])
            return missing_cards
            #logger.info(missing_cards)

    def __get_card_data_from_mtgjson(self, setsymbol):
        self.__cards_in_set_mtgjson_df = GetDataForSetFromMTGJson(setsymbol)

    def __populate_cards_in_set_df(self, pack):
        try:
            #logger.info(pack['event_name'])
            parts = pack['event_name'].split('_')
            second_term = parts[1]
            if second_term=="RemixDraft":
                second_term = "Chaos"
            logger.info("getting card data for set "+second_term)
            self.__get_card_data_from_mtgjson(second_term)
            self.__cards_in_set_df = get_card_data_for_set(second_term)
            if self.__cards_in_set_df is None:
                if self.__set_data_not_available is False:
                    self.__set_data_not_available = True       
        except Exception as e:
            # Handle any exception thrown by get_card_positions
            print(f"Error with __populate_cards_in_set_df: {e}")        


    def __sort_pack(self, pack):
        # Get card info for each card in the pack
        card_packdebug_info = [get_card_packdebug_info(card_id, self.__cards_in_set_mtgjson_df) for card_id in pack['card_ids']]
        
        # Define a custom sorting key function
        def sort_key(card):
            # Define rarity order
            rarity_order = {'mythic': 0, 'rare': 1, 'uncommon': 2, 'common': 3}
            
            # Get rarity and number, use default values if not present
            rarity = card.get('rarity', 'common').lower()
            number = card.get('number', '0')
            
            # Convert number to int if possible, otherwise use string
            try:
                number = int(number)
            except ValueError:
                pass
            
            # Return tuple for sorting: (rarity_order, number)
            return (rarity_order.get(rarity, 4), number)
        
        # Sort the card_packdebug_info list
        sorted_card_info = sorted(card_packdebug_info, key=sort_key)
        
        # Extract sorted card_ids
        sorted_card_ids = [card['id'] for card in sorted_card_info if 'id' in card]
        
        # Update the pack with sorted card_ids
        pack['card_ids'] = sorted_card_ids
        return pack, card_packdebug_info


    def __update_overlays(self):
        # Implement the logic to update overlays here
        # This method should be called regularly to reflect any UI changes
        if self.__currentScene != "Draft":
            return
        try:
            if self.__check_for_new_overlays():
                #logger.info(self.__last_pack)
                logger.info("we need to update overlays")
                self.__only_show_overlay()
                #self.__prep_and_show_overlay(self.__last_pack)
            
        except Exception as e:
            logger.error(f"Error updating overlays: {e}")

    def __check_for_new_overlays(self):
        # Implement logic to check if new overlays need to be created
        #logger.info("check if we need to update overlays")

        try:
            card_positions = get_card_positions(len(self.__last_pack['card_ids']))
        except Exception as e:
            logger.error(f"Error getting card positions: {e}")
            return False
        #logger.info("card_positions: "+str(card_positions))
        #logger.info("__last_card_positions: "+str(self.__last_card_positions))
        if card_positions:
            if self.__last_card_positions != card_positions:
                logger.info("New card positions detected, updating overlays")
                self.__last_card_positions = card_positions
                return True
        
        logger.info("No update needed for overlays")
        return False

    def __only_show_overlay(self):
        self.last_overlay_update = time.time()
        try:
            card_positions = get_card_positions(len(self.__last_pack['card_ids']))
            #logger.info("get card positions complete")
        except Exception as e:
            logger.info(f"Error in calling function: {str(e)}")                
        if card_positions:
            self.__last_card_positions = card_positions
            #for card_position in card_positions:
            #    logger.info(card_position)
            #card_stats_with_gihwr = [get_card_stats_for_overlay(card_id, self.__cards_in_set_df) for card_id in pack['card_ids']]

            #logger.info(card_positions)
            #logger.info(card_stats_with_gihwr)
            card_overlays = []
            i = 0
            #logger.info(card_details_withstats)
            #logger.info(len(card_details_withstats))
            #logger.info(len(card_positions))
            if len(self.__last_card_details_withstats) != len(card_positions):
                logger.info("mismatch between detected cards on screen and cards in pack")
                #self.__overlay_manager.hide_overlay()
                return
            for card_stats in self.__last_card_details_withstats:
                #logger.info(card_stats[0])
                #logger.info(card_positions[i])
                #logger.info(i)
                card_overlays.append([card_stats[0], card_positions[i]])
                i = i + 1            
            #logger.info("Card overlays: "+str(card_overlays))
            #logger.info(pack_info)
            self.show_all_overlays(card_overlays, self.__last_pack_info)
    
    def show_all_overlays(self, card_overlays, pack_info):
        #self.overlay_update_signal.emit(card_overlays, pack_info)        
        self.follower_thread.update_overlay(card_overlays, self.__last_pack_info)

    def __prep_and_show_overlay(self, pack):
        try:
            self.__last_pack = pack
            if self.__cards_in_set_df is None:
                if not self.__set_data_not_available:
                    self.__populate_cards_in_set_df(pack)        
            missing_cards = self.__update_draft_opens(pack)
            #pack_info = f"Pack {pack['pack_number']}, Pick {pack['pick_number']}\nCards:"
            pack_info = ""
            
            pack, card_packdebug_info = self.__sort_pack(pack)
            
            if self.__cards_in_set_df is None:
                #data not available yet so we use mtgjson data without stats
                self.__last_card_details_withstats = [get_card_info(card_id, self.__cards_in_set_mtgjson_df) for card_id in pack['card_ids']]
            else:
                self.__last_card_details_withstats = [get_card_info(card_id, self.__cards_in_set_df) for card_id in pack['card_ids']]

            #debug a full pack:
            if len(pack['card_ids']) > 13:
                output_string = "\n\n############Cards in pack:############\n"
                for card in card_packdebug_info:
                    output_string += str(card['rarity']) + " | "
                    output_string += str(card['number']) + " | "
                    output_string += str(card['name']) + "\n"
                logger.info(output_string)

            #card_details_withstats.sort(key=lambda x: x[1], reverse=True)
            #card_details = [card[0] for card in card_details_withstats]
            #pack_info += "\n" + "\n".join(card_details)

            if missing_cards is not None:
                missing_card_names = [get_card_info(card_id, self.__cards_in_set_mtgjson_df) for card_id in missing_cards]
                missing_card_names_output = [card[0] for card in missing_card_names]
                pack_info += "\n" + "Cards that are missing: "
                pack_info += "\n" + "\n".join(missing_card_names_output)

            self.__last_pack_info = pack_info
            #self.__only_show_overlay()
            if (self.debug_mode):
                input("Press Enter to continue to the next entry...")     
        except Exception as e:
            # Handle any exception thrown by get_card_positions
            print(f"Error with prep and show overlay: {e}")                   
             
    def __handle_bot_draft_pick(self, json_obj):
        """Handle 'Draft.MakePick messages."""
        self.__clear_game_data()

        try:
            self.cur_draft_event = json_obj['EventName']
            pick = {
                'event_name': json_obj['EventName'],
                'pack_number': int(json_obj['PackNumber']),
                'pick_number': int(json_obj['PickNumber']),
                'card_id': int(json_obj['CardId']),
            }
            #logger.info(f'Draft pick: {pick}')
            self._api_client.submit_draft_pick(self._add_base_api_data(pick))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing draft pick from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_scenechange(self, json_obj):
        #logger.info(json_obj['fromSceneName'])
        if json_obj['fromSceneName']=="Draft":
            #self.__overlay_manager.hide_overlay()
            self._reinitialize()
        elif json_obj['toSceneName']=="Draft":
            self.__currentScene = "Draft"

    def __handle_joined_pod(self, json_obj):
        """Handle 'Event_Join' messages."""
        self.__clear_game_data()

        try:
            self.cur_draft_event = json_obj['EventName']
            logger.info(f'Joined draft pod: {self.cur_draft_event}')
            self.__draft_opens = DraftOpens()

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing join pod event from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_human_draft_combined(self, json_obj):
        """Handle combined human draft pack/pick messages."""
        self.__clear_game_data()

        try:
            self.cur_draft_event = json_obj['EventId']
            pack = {
                'draft_id': json_obj['DraftId'],
                'event_name': json_obj['EventId'],
                'pack_number': int(json_obj['PackNumber']),
                'pick_number': int(json_obj['PickNumber']),
                'card_ids': json_obj['CardsInPack'],
                'method': 'LogBusiness',
            }
            #logger.info(f'Human draft pack (combined): {pack}')
            self.__prep_and_show_overlay(pack)
            self._api_client.submit_human_draft_pack(self._add_base_api_data(pack))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing human draft pack from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

        try:
            pick = {
                'draft_id': json_obj['DraftId'],
                'event_name': json_obj['EventId'],
                'pack_number': int(json_obj['PackNumber']),
                'pick_number': int(json_obj['PickNumber']),
                'card_id': int(json_obj['PickGrpId']),
                'auto_pick': json_obj['AutoPick'],
                'time_remaining': json_obj['TimeRemainingOnPick'],
            }
            #logger.info(f'Human draft pick (combined): {pick}')
            self._api_client.submit_human_draft_pick(self._add_base_api_data(pick))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing human draft pick from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_human_draft_pack(self, json_obj):
        """Handle 'Draft.Notify' messages."""
        self.__clear_game_data()
        try:
            pack = {
                'draft_id': json_obj['draftId'],
                'event_name': self.cur_draft_event,
                'pack_number': int(json_obj['SelfPack']),
                'pick_number': int(json_obj['SelfPick']),
                'card_ids': [int(x) for x in json_obj['PackCards'].split(',')],
                'method': 'Draft.Notify',
            }
            #logger.info(f'Human draft pack (Draft.Notify): {pack}')
            self.__prep_and_show_overlay(pack)
            self._api_client.submit_human_draft_pack(self._add_base_api_data(pack))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing human draft pack from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_deck_submission(self, json_obj):
        """Handle 'Event_SetDeck' messages."""
        self.__clear_game_data()

        try:
            decks = json_obj['Deck']
            deck = {
                'event_name': json_obj['EventName'],
                'maindeck_card_ids': [d['cardId'] for d in decks['MainDeck'] for i in range(d['quantity'])],
                'sideboard_card_ids': [d['cardId'] for d in decks['Sideboard'] for i in range(d['quantity'])],
                'companion': decks['Companions'][0]['cardId'] if len(decks['Companions']) > 0 else 0,
                'is_during_match': False,
            }
            logger.info(f'Deck submission (Event_SetDeck): {deck}')
            self._api_client.submit_deck_submission(self._add_base_api_data(deck))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing deck submission from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_self_rank_info(self, json_obj):
        """Handle 'Rank_GetCombinedRankInfo' messages."""
        try:
            self.cur_rank_data = json_obj
            self.cur_user = json_obj.get('playerId', self.cur_user)
            logger.info(f'Parsed rank info for {self.cur_user}: {self.cur_rank_data}')
            data = {
                'rank_data': self.cur_rank_data,
                'limited_rank': None,
                'constructed_rank': None,
            }
            self._api_client.submit_rank(self._add_base_api_data(data))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing self rank info from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_collection(self, json_obj):
        """Handle 'PlayerInventory.GetPlayerCardsV3' messages."""
        if self.cur_user is None:
            logger.info(f'Skipping collection submission because player id is still unknown')
            return

        collection = {
            'card_counts': json_obj,
        }
        logger.info(f'Collection submission of {len(json_obj)} cards')
        self._api_client.submit_collection(self._add_base_api_data(collection))

    def __handle_inventory(self, json_obj):
        """Handle 'InventoryInfo' messages."""
        try:
            json_obj = {k: v for k, v in json_obj.items() if k in {
                'Gems',
                'Gold',
                'TotalVaultProgress',
                'wcTrackPosition',
                'WildCardCommons',
                'WildCardUnCommons',
                'WildCardRares',
                'WildCardMythics',
                'DraftTokens',
                'SealedTokens',
                'Boosters',
                'Changes',
            }}
            blob = {
                'inventory': json_obj,
            }
            logger.info(f'Submitting inventory: {blob}')
            self._api_client.submit_inventory(self._add_base_api_data(blob))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing inventory from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __handle_player_progress(self, json_obj):
        """Handle mastery pass messages."""
        return
        try:
            blob = {
                'progress': json_obj,
            }
            logger.info(f'Submitting mastery progress')
            self._api_client.submit_player_progress(self._add_base_api_data(blob))

        except Exception as e:
            self._log_error(
                message=f'Error {e} parsing mastery progress from {json_obj}',
                error=e,
                stacktrace=traceback.format_exc(),
            )

    def __reset_current_user(self):
        logger.info('User logged out from MTGA')
        if self.cur_user is not None:
            self.disconnected_user = self.cur_user
            self.disconnected_screen_name = self.user_screen_name
            self.disconnected_rank = self.cur_rank_data

        self.cur_user = None
        self.user_screen_name = None
        self.cur_rank_data = None

    def __handle_reconnect_result(self):
        logger.info('Reconnected - restoring prior user info')

        self.cur_user = self.disconnected_user
        self.user_screen_name = self.disconnected_screen_name
        self.cur_rank_data = self.disconnected_rank


def validate_uuid_v4(maybe_uuid):
    if maybe_uuid is None:
        return None
    try:
        uuid.UUID(maybe_uuid, version=4)
        return maybe_uuid
    except ValueError:
        return None

def get_client_token_mac():
    message = TOKEN_ENTRY_MESSAGE
    while True:
        token = subprocess.run(['osascript', '-e', f'text returned of (display dialog "{message}" default answer "" with title "{TOKEN_ENTRY_TITLE}")'],
            capture_output=True, text=True).stdout.strip()

        if token == '':
            show_dialog_mac(TOKEN_MISSING_TITLE, TOKEN_MISSING_MESSAGE)
            exit(1)

        if validate_uuid_v4(token) is None:
            message = TOKEN_INVALID_MESSAGE
        else:
            return token

def get_client_token_tkinter():
    import tkinter
    import tkinter.simpledialog
    import tkinter.messagebox

    window = tkinter.Tk()
    window.wm_withdraw()

    message = TOKEN_ENTRY_MESSAGE
    while True:
        token = tkinter.simpledialog.askstring(TOKEN_ENTRY_TITLE, message)

        if token is None:
            tkinter.messagebox.showerror(TOKEN_MISSING_TITLE, TOKEN_MISSING_MESSAGE)
            exit(1)

        if validate_uuid_v4(token) is None:
            message = TOKEN_INVALID_MESSAGE
        else:
            return token

def get_client_token_visual():
    if sys.platform == 'darwin':
        return get_client_token_mac()
    else:
        return get_client_token_tkinter()

def get_client_token_cli():
    message = TOKEN_ENTRY_MESSAGE
    while True:
        token = input(message)

        if token is None:
            print(TOKEN_MISSING_MESSAGE)
            exit(1)

        if validate_uuid_v4(token) is None:
            message = f'{TOKEN_INVALID_MESSAGE} Token: '
        else:
            return token

def get_config():
    import configparser
    token = None
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if 'client' in config:
            token = validate_uuid_v4(config['client'].get('token'))

    if token is None or validate_uuid_v4(token) is None:
        try:
            token = get_client_token_visual()
        except ModuleNotFoundError:
            token = get_client_token_cli()

        if 'client' not in config:
            config['client'] = {}
        config['client']['token'] = token
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)

    return token

def show_dialog_mac(title, message):
    subprocess.run(['osascript', '-e', f'display dialog "{message}" with title "{title}" buttons {{"OK"}} default button "OK"'], capture_output=True)

def show_dialog_tkinter(title, message):
    import tkinter
    import tkinter.messagebox
    window = tkinter.Tk()
    window.wm_withdraw()
    tkinter.messagebox.showerror(title, message)

def show_message(title, message):
    try:
        if sys.platform == 'darwin':
            return show_dialog_mac(title, message)
        else:
            return show_dialog_tkinter(title, message)
    except ModuleNotFoundError:
        logger.exception('Could not suitably show message')
        logger.warning(message)

def show_update_message(response_data):
    title = '17Lands'
    if 'upgrade_instructions' in response_data:
        message = response_data['upgrade_instructions']
    else:
        message = ('17Lands update required! The minimum supported version for the client is '
            + f'{response_data.get("min_version", "newer than your current version")}. '
            + f'Your current version is {CLIENT_VERSION}. Please update with one of the following '
            + 'commands in the terminal, depending on your installation method:\n'
            + 'brew update && brew upgrade seventeenlands\n'
            + 'pip3 install --user --upgrade seventeenlands')

    show_message(title, message)

def verify_version(host, prompt_if_update_required):
    api_client = seventeenlands.api_client.ApiClient(host=host)
    response = api_client.get_client_version_info(params={
        'client': 'python',
        'version': CLIENT_VERSION[:-2],
    })

    logger.info(f'Got minimum client version response: {response.text}')
    blob = json.loads(response.text)
    this_version = [int(i) for i in CLIENT_VERSION.split('.')[:-1]]
    min_supported_version = [int(i) for i in blob['min_version'].split('.')]
    logger.info(f'Minimum supported version: {min_supported_version}; this version: {this_version}')

    if this_version >= min_supported_version:
        return True

    if prompt_if_update_required:
        show_update_message(blob)

    return False


# def processing_loop(args, token, overlay_manager):
#     filepaths = POSSIBLE_CURRENT_FILEPATHS
#     if args.log_file is not None:
#         filepaths = (args.log_file, )

#     follow = not args.once

#     follower = Follower(token, overlay_manager, host=args.host, debug_mode=args.debug_mode)

#     # if running in "normal" mode...
#     #if (
#     #    args.log_file is None
#     #    and args.host == seventeenlands.api_client.DEFAULT_HOST
#     #    and follow
#     #):
#         # parse previous log once at startup to catch up on any missed events
#         #for filename in POSSIBLE_PREVIOUS_FILEPATHS:
#         #    if os.path.exists(filename):
#         #        logger.info(f'Parsing the previous log {filename} once')
#         #        follower.parse_log(filename=filename, follow=False)
#         #        break

#     # tail and parse current logfile to handle ongoing events
#     any_found = False
#     for filename in filepaths:
#         if os.path.exists(filename):
#             any_found = True
#             logger.info(f'Following along {filename}')
#             #try this
#             threading.Thread(target=follower.parse_log, args=(filename, follow), daemon=True).start()

#             #follower.parse_log(filename=filename, follow=follow)
#             overlay_manager.run()

#     if not any_found:
#         logger.warning("Found no files to parse. Try to find Arena's Player.log file and pass it as an argument with -l")

#     logger.info(f'Exiting')

class FollowerThread(QThread):
    overlay_update_signal = pyqtSignal(list, str)

    def __init__(self, token, host, debug_mode, log_file, once):
        super().__init__()
        self.token = token
        self.host = host
        self.debug_mode = debug_mode
        self.log_file = log_file
        self.once = once
        self.follower = None

    def run(self):
        self.follower = Follower(self.token, self, host=self.host, debug_mode=self.debug_mode)
        filepaths = POSSIBLE_CURRENT_FILEPATHS if self.log_file is None else (self.log_file,)
        
        for filename in filepaths:
            if os.path.exists(filename):
                self.follower.parse_log(filename=filename, follow=not self.once)
                break
        else:
            logger.warning("Found no files to parse. Try to find Arena's Player.log file and pass it as an argument with -l")

    def update_overlay(self, card_overlays, pack_info):
        self.overlay_update_signal.emit(card_overlays, pack_info)

def main():
    app = QApplication(sys.argv)    

    parser = argparse.ArgumentParser(description='MTGA log follower')

    #app = QApplication(sys.argv)
    #manager = OverlayManager()
    #overlay_manager = get_overlay_manager()

    config_token = get_config()

    parser.add_argument('-l', '--log_file',
        help=f'Log filename to process. If not specified, will try one of {POSSIBLE_CURRENT_FILEPATHS}')
    parser.add_argument('--host', default=seventeenlands.api_client.DEFAULT_HOST,
        help=f'Host to submit requests to. If not specified, will use {seventeenlands.api_client.DEFAULT_HOST}')
    parser.add_argument('--token', default=config_token,
                        help=f'Token of the user. If not specified, will use the token at {CONFIG_FILE}')
    parser.add_argument('--once', action='store_true',
        help='Whether to stop after parsing the file once (default is to continue waiting for updates to the file)')
    parser.add_argument('-debug_mode', default=False)
    #args.debug_mode

    args = parser.parse_args()

    check_count = 0
    while not verify_version(
        host=args.host,
        prompt_if_update_required=check_count % UPDATE_PROMPT_FREQUENCY == 0,
    ):
        check_count += 1
        time.sleep(UPDATE_CHECK_INTERVAL.total_seconds())

    token = args.token
    logger.info(f'Using token {token[:4]}...{token[-4:]}')


    overlay_manager = OverlayManager()
    
    follower_thread = FollowerThread(token, args.host, args.debug_mode, args.log_file, args.once)
    follower_thread.overlay_update_signal.connect(overlay_manager.show_all_overlays)
    follower_thread.start()
    overlay_manager.run()
    sys.exit(app.exec_())
    #processing_loop(args, token, overlay_manager)


if __name__ == '__main__':
    main()
