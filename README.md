usage:

pip install -r requirements.txt to get all required libraries

python mtga_follower.py

load up arena and watch the magic

todo: 

move card set and overlay logic out of follower code into apiclient

change apiclient to no longer hit seventeenlands

change apiclient to maintain card set info and invoke overlay

update carddata to calc winrate columns for monocolored, color pairs, wedges/shards, and 5cc

add support in apiclient to grab that info for all cards in pack and send it all up to overlay

add support in overlay to only display data for all data or for filtered data by deck colors

add buttons in overlay to enable above filter toggling

make UI not shitty
