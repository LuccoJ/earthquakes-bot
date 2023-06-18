# Brainstorm earthquake and emergency alert bot

This is the earthquake early warning and reporting bot known as Brainstorm on IRC, BrainstormBot on Twitter and u/BrainstormBot on Reddit.

See https://www.reddit.com/r/EEW/wiki/index for a general introduction.

The code provided here is by no means ready-to-run and requires outdated and deprecated tools (Python 2.7 and the Poetry version to go with it to start with, as well as a number of dependencies Poetry will attempt to pull in) as well as possibly some modules that I haven't been able to provide as they have too many internal dependencies.
It is very scarcely documented in terms of comments.

As a whole, it depends on an IRC bot core to run, even though it sends messages to many more places than just IRC. Bot cores of the "Phenny" family may work with or without modifications to this code.

You will have to generate a cities.geojson file as explained in tables/cities.py, and you will also need a bot configuration files listing whatever earthquake feeds you have at your disposal that the bot can parse (RSS, Atom, QuakeML, FDSN, CSV, etc), and, if Twitter stuff still worked, which it doesn't thanks to the small pricing changes Elon Musk decided to put on accessing the Twitter API, you'd also need to be following a number of earthquake reporting agencies, to get official earthquake reports in as timely a way as possible.
The early warning part just won't work at all anymore, unless you manage to port it to the Twitter streaming API version 2 (it uses version 1, which has been killed), and have the money to pay through the nose for accessing that.

I do not plan to work on this bot anymore due to its distinguishing features being based on Twitter APIs that I can no longer access. I may polish the code a little, if I have nothing else to do, to make it easier to run for anyone who wants to.

---

![TLDR](https://imgs.xkcd.com/comics/seismic_waves.png)  ­—[xkcd](https://xkcd.com/723/), years before Brainstorm existed

#Source code

The source code of the earthquake warning/reporting part of my bot is found at https://github.com/LuccoJ/earthquakes-bot but it won't work without an IRC bot core, and it will probably need tweaking for missing libraries and generally for using long-deprecated stuff (Python 2.7 and Poetry for Python 2.7, and many Python 2.7 dependencies from PyPi). It will also need a configuration file with earthquake report sources (RSS, Atom, QuakeML, FDSN, CSV, etc, earthquake feeds).

#Important note about Twitter

[Twitter announced closing down its API to all free users](https://twitter.com/TwitterDev/status/1621026986784337922) on February 9, 2023. Since March 15, the streaming API that I rely on has become unaccessible to free users.

This bot's entire concept for early warnings, and also many of the later but still timely reports, is based on parsing a Twitter stream in real time, looking for keywords and well-known posters. As such, while the bot will continue to function in a diminished capacity, it will no longer work on Twitter, and it won't offer much value anymore.

You can follow Brainstorm [on Mastodon](https://botsin.space/@brainstorm/109796476782694371), [on Matrix](https://matrix.to/#/#earthquakes:matrix.org), or [on IRC](https://web.libera.chat/##earthquakes), but you will not be able to receive personalized warnings in private messages, unless you contact me on IRC or Matrix with your location (there is a glitch with the bot sending private messages to Matrix though currently).

I also would like to suggest leaving Twitter and Reddit and finding somewhere else to be. It is a place that has become hostile to its users and companies that invested time and money in it, thanks to someone who behaves like a rich child with a new toy to break.

#Where to find Brainstorm

* [Matrix](https://matrix.org) in the rooms [#earthquakes:matrix.org](https://matrix.to/#/#earthquakes:matrix.org) and [#alerts:matrix.org](https://matrix.to/#/#warnings:matrix.org)
* [Mastodon](https://joinmastodon.org/) as [@brainstorm@botsin.space](https://botsin.space/@brainstorm)
* [Libera.chat](https://libera.chat) in [##earthquakes](https://web.libera.chat/##earthquakes)

#How Brainstorm works

Brainstorm gets earthquake information from mainly two types of sources: posts on [Twitter](https://twitter.com/BrainstormBot), and official reports by various geophysical agencies. Some specific Twitter accounts are monitored by Brainstorm for messages in a standard format, and these are generally in turn provided by geophysical agencies, while other tweets are simply received from accounts of people tweeting about an earthquake they felt.

This is how **the Twitter analysis** works in detail:

* Twitter has a [streaming API](https://dev.twitter.com/streaming/public) that the bot queries to receive all tweets containing one among a list of keywords (at most 400 can be specified); any tweet containing any of those keywords is delivered in real time.
* Brainstorm opens the stream with a list of the word "earthquake" translated into all many major world languages, so any tweet containing the equivalent word to "earthquake" will be received; it also listens for specific Twitter accounts expected to send messages in a known format.
* It discards most of those tweets, and only keeps the ones that contain [geolocation](https://en.wikipedia.org/wiki/Geolocation) information in some shape or form: some of them are directly geolocated by Twitter (e.g. ones sent from mobile devices), for others the location is determined from the user's profile, and for some a name of a city can be found in the tweet itself. Brainstorm tries all these options in order of preference, and if none works, then it forgets about that specific tweet.
* If the tweet can be geolocated, it makes sure the "earthquake"-like word it contains actually matches the language the tweet is written in (Twitter tells you which language the tweet is in, so that's easy), so that false positives from the word for "earthquake" in one language meaning something very common in another language are avoided
* Then, Brainstorm assigns a "score" to the tweet based on several factors: for instance, if the tweet is short, its score is higher, and it's also higher if it is in capitals or contains exclamation marks, while if it contains a URL or a [magnitude](https://en.wikipedia.org/wiki/Richter_magnitude_scale), that likely means it refers to an earthquake that happened in the past, so the score is lowered. Other heuristics are used.
* If the tweet is from a monitored account, then instead of assigning scores heuristically, an exact time, location and magnitude are read from the tweet text itself and considered more authoritative.
* Eventually, Brainstorm creates a preliminary "report" of a potential earthquake based on the tweet, if conditions are satisfied.
* If multiple tweets with overlapping locations in their "reports" add up to a certain score, then that is considered an "event", with epicenter in the central location of the recorded tweets, and a very inaccurately guessed magnitude and felt radius based on the presence or absence of further keywords ("strong", "weak", "terrible", etc).
* Events above a certain magnitude, or located in certain areas, or meeting other criteria, are sent to different internet locations (various IRC channels, Twitter, Matrix and Reddit). Brainstorm decices whether to send a simple "Preliminary" report, or an "earthquake warning", by estimating when the earthquake actually took place based on the first tweet seemingly referring to it, and on whether the guessed magnitude would make it plausible for some people who will be affected by the earthquake to have yet to be reached by its [S-waves](https://en.wikipedia.org/wiki/S-wave).
* For users that Brainstorm knows the location of (based on manual input, or their Twitter profile), a private message is also sent on IRC, Matrix and Twitter if they are deemed to have felt or be about to feel the tremors.

It is simpler to process **data from official sources**, as the main concern is just to disseminate the same event once even if multiple sources report it multiple times, unless its estimated parameters have considerably changed:

* Several geophysical institutes are monitored, using [RSS](https://en.wikipedia.org/wiki/RSS) feeds, or [FDSN](https://en.wikipedia.org/wiki/International_Federation_of_Digital_Seismograph_Networks) / [QuakeML](https://en.wikipedia.org/wiki/QuakeML) feeds, or (only in one case, at the time being) [GeoJSON](https://en.wikipedia.org/wiki/GeoJSON) [websockets](https://en.wikipedia.org/wiki/WebSocket), which, unlike the former two options, permits realtime monitoring (similar to the Twitter streaming API, but less centralized) instead of only periodic queries.
* When a new event is recorded from a source, it is immediately assigned to a report that has a score of 1, meaning it will be disseminated immediately, unlike tweets which have much lower scores until enough of them have been received to assume a valid event has occurred.
* These sources normally provide explicit information about time and place coordinates, depth, and magnitude, so these are used directly, and a report is considered part of a previous event, and not disseminated again, unless some of these parameters deviate considerably.
* Some sources also provide a level of alert (green, yellow, amber or red) based on the estimated impact on populations, and these are reported as new information when they change.

Brainstorm also adds some **information of its own**, which mainly consists of data elaborated from OpenStreetMap:

* coordinates-to-toponym resolution, including a database of [Flinn-Engdahl regions](https://en.wikipedia.org/wiki/Flinn%E2%80%93Engdahl_regions)
* amount of people likely affected, based on the estimated felt radius
* any nuclear reactors in the felt radius of the earthquakes
* [webcams](http://www.webcams.travel/) reported as providing real-time imagery in the earthquake area
* whether the earthquake occurred on the land or in the sea, and whether the magnitude and depth are likely to generate a [tsunami](https://en.wikipedia.org/wiki/Tsunami), which is disseminated as a separate warning
