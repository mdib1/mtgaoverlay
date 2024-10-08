import pandas as pd
import io
import os
import requests
import gzip
import datetime
import json

card_csv_url = "https://17lands-public.s3.amazonaws.com/analysis_data/cards/cards.csv"
#url = "https://17lands-public.s3.amazonaws.com/analysis_data/game_data/game_data_public.BLB.PremierDraft.csv.gz"
#91603

def downloadMTGJsonDataForSet(setsymbol):
    file_path = setsymbol+".json"
    if os.path.exists(file_path):
        # File exists, so we'll read and return its contents
        with open(file_path, 'r') as json_file:
            return json.load(json_file)    
    else:
        url = "https://mtgjson.com/api/v5/"+file_path
        response = requests.get(url)
        data = response.json()
        with open(file_path, 'w') as json_file:
            json.dump(data, json_file, indent=4)
        return data

def GetDataForSetFromMTGJson(setsymbol):
    file_name = setsymbol+"_MTGJson.csv"
    if os.path.exists(file_name):
        card_data = pd.read_csv(file_name)
        return card_data
    else:
        data = downloadMTGJsonDataForSet(setsymbol)
        columns = ['id', 'expansion', 'name', 'rarity', 'color_identity', 'mana_value', 
               'types', 'boosterTypes','number']
    
        # Create a list to hold our processed card data
        processed_cards = []    
        for card in data['data']['cards']:
            arena_id = card['identifiers'].get('mtgArenaId')
            if arena_id is not None:
                processed_card = {
                    'id': arena_id,
                    'expansion': setsymbol,
                    'name': card['name'],
                    'rarity': card.get('rarity'),
                    'color_identity': ','.join(card.get('colorIdentity', [])),  # Join list into string
                    'mana_value': card.get('manaValue'),
                    'types': [], #','.join(card.get('types', [])),  # Join list into string
                    'boosterTypes':card.get('boosterTypes'),
                    'number':card.get('number')
                }
                processed_cards.append(processed_card)
        df = pd.DataFrame(processed_cards, columns=columns)       
        df.to_csv(file_name, index=False) 
        return df


def get_card_data():
    cards_df = pd.read_csv(card_csv_url)
    return cards_df

def get_name_from_id(cards_df, card_id):
    # Try to find the card with the given ID
    card = cards_df[cards_df['id'] == card_id]
    
    # If a card is found, return its name
    if not card.empty:
        return card['name'].iloc[0]
    else:
        return f"No card found with ID: {card_id}"

def get_game_data(setsymbol, draftformat = "PremierDraft"):
    url = "https://17lands-public.s3.amazonaws.com/analysis_data/game_data/game_data_public."+setsymbol+"."+draftformat+".csv.gz"
    try:
        game_df = load_gzipped_csv_from_url(url)
        return game_df        
    except Exception as e:
        print(f"An error occurred: {e}")    

def load_gzipped_csv_from_url(url):
    # Send a GET request to the URL
    response = requests.get(url)
    
    # Check if the request was successful
    if response.status_code == 200:
        # Decompress the gzipped content
        decompressed_content = gzip.decompress(response.content)
        
        # Create a StringIO object from the decompressed content
        csv_file = io.StringIO(decompressed_content.decode('utf-8'))
        
        # Read the CSV file into a pandas DataFrame
        df = pd.read_csv(csv_file)
        
        return df
    else:
        raise Exception(f"HTTP error {response.status_code}: {response.reason}")


# expansion
# event_type
# draft_id
# draft_time
# game_time
# build_index
# match_number
# game_number
# rank
# opp_rank
# main_colors
# splash_colors
# on_play
# num_mulligans
# opp_num_mulligans
# opp_colors
# num_turns
# won
# user_n_games_bucket
# user_game_win_rate_bucket
#opening_hand_Bark-Knuckle Boxer
#drawn_Bark-Knuckle Boxer
#tutored_Bark-Knuckle Boxer
#deck_Bark-Knuckle Boxer
#sideboard_Bark-Knuckle Boxer

def filter_game_data_to_set(setsymbol, game_df, cards_df):
    cards_in_set_df = cards_df[cards_df['expansion'] == setsymbol].copy()  # Use copy() to avoid modifying the original DataFrame
    # Initialize columns
    cards_in_set_df['GDWR'] = None
    cards_in_set_df['OHWR'] = None
    cards_in_set_df['GIHWR'] = None
    for card in cards_in_set_df['name']:
        drawn_col_name = "drawn_" + card
        opening_hand_col_name = "opening_hand_" + card
        # Check if the columns exist
        if drawn_col_name in game_df.columns and opening_hand_col_name in game_df.columns:
            # GDWR: Calculate directly
            drawn_count = game_df[drawn_col_name].sum()  # Number of times card was drawn
            drawn_game_won_count = game_df[(game_df[drawn_col_name] == 1) & (game_df['won'] == True)].shape[0]
            GDWR = drawn_game_won_count / drawn_count if drawn_count > 0 else None
            # OHWR: Calculate directly
            opening_hand_count = game_df[opening_hand_col_name].sum()  # Number of times card was in opening hand
            opening_hand_game_won_count = game_df[(game_df[opening_hand_col_name] == 1) & (game_df['won'] == True)].shape[0]
            OHWR = opening_hand_game_won_count / opening_hand_count if opening_hand_count > 0 else None
            # GIHWR: Calculate directly
            GIH_count = ((game_df[drawn_col_name] == 1) | (game_df[opening_hand_col_name] == 1)).sum()
            GIH_game_won_count = game_df[((game_df[drawn_col_name] == 1) | (game_df[opening_hand_col_name] == 1)) & (game_df['won'] == True)].shape[0]
            GIHWR = GIH_game_won_count / GIH_count if GIH_count > 0 else None
            # Assign the calculated values using .loc with the card's index
            cards_in_set_df.loc[cards_in_set_df['name'] == card, 'GDWR'] = GDWR
            cards_in_set_df.loc[cards_in_set_df['name'] == card, 'OHWR'] = OHWR
            cards_in_set_df.loc[cards_in_set_df['name'] == card, 'GIHWR'] = GIHWR   
    return cards_in_set_df


def redownload_card_data_for_set(setsymbol, file_name):
    cards_df = get_card_data()
    game_df = get_game_data(setsymbol)
    if game_df is None:
        return None
    cards_in_set_df = filter_game_data_to_set(setsymbol, game_df, cards_df)
    if cards_in_set_df.shape[0] > 0:
        #redownload_card_data() no idea why i left this here
        cards_in_set_df.to_csv(file_name, index=False)
    else:
        return None
    return cards_in_set_df    

def get_card_data_for_set(setsymbol):
    file_name = setsymbol+".csv"
    if os.path.exists(file_name):
        modification_time = os.path.getmtime(file_name)
        modification_datetime = datetime.datetime.fromtimestamp(modification_time)
        today = datetime.date.today()
        if modification_datetime.date() < today:
            print("Card data for "+setsymbol+" is older than today, redownloading")
            return redownload_card_data_for_set(setsymbol, file_name)
        else:
            print("Card data for "+setsymbol+" is fresh, reusing saved data")
            card_data = pd.read_csv(file_name)
            return card_data
    else:
        return redownload_card_data_for_set(setsymbol, file_name)


if __name__ == '__main__':
    main()
