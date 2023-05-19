# Brainstorm earthquake and emergency alert bot

This is the earthquake early warning and reporting bot known as Brainstorm on IRC, BrainstormBot on Twitter and u/BrainstormBot on Reddit.

See https://www.reddit.com/r/EEW/wiki/index for a general introduction.

The code provided here is by no means ready-to-run and requires outdated and deprecated tools (Python 2.7 and the Poetry version to go with it to start with, as well as a number of dependencies Poetry will attempt to pull in) as well as possibly some modules that I haven't been able to provide as they have too many internal dependencies.
It is very scarcely documented in terms of comments.

As a whole, it depends on an IRC bot core to run, even though it sends messages to many more places than just IRC. Bot cores of the "Phenny" family may work with or without modifications to this code.

You will have to generate a cities.geojson file as explained in tables/cities.py, and you will also need a bot configuration files listing whatever earthquake feeds you have at your disposal that the bot can parse, and, if Twitter stuff still worked, which it doesn't thanks to the small pricing changes Elon Musk decided to put on accessing the Twitter API, you'd also need to be following a number of earthquake reporting agencies, to get official earthquake reports in as timely a way as possible.
The early warning part just won't work at all anymore, unless you manage to port it to the Twitter streaming API version 2 (it uses version 1, which has been killed), and have the money to pay through the nose for accessing that.

I do not plan to work on this bot anymore due to its distinguishing features being based on Twitter APIs that I can no longer access. I may polish the code a little, if I have nothing else to do, to make it easier to run for anyone who wants to.
