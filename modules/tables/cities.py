#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
cities.py - Geolocating module to quickly obtain coordinates of a city from names

This file is part of the "Brainstorm" distribution (https://github.com/luccoj/earthquakes-bot).
Copyright (c) 2016-2023 Lorenzo J. Lucchini (ljlbox@tiscali.it)

This program is free software: you can redistribute it and/or modify  
it under the terms of the GNU General Public License as published by  
the Free Software Foundation, version 3.
This program is distributed in the hope that it will be useful, but 
WITHOUT ANY WARRANTY; without even the implied warranty of 
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU 
General Public License for more details.
You should have received a copy of the GNU General Public License 
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

"""
This file requires a 'cities.json' file located in the same directory to work,
which contains the actual city location data.

That is obtainable from free data at https://query.wikidata.org/ using this query:

SELECT DISTINCT ?city ?label ?lang ?coords ?population WHERE {
    ?city wdt:P31/wdt:P279* wd:Q7930989 .
    ?city wdt:P1082 ?population .
    ?city wdt:P625 ?coords .
    ?city (rdfs:label|skos:altLabel) ?label
    bind (lang(?label) AS ?lang).
    filter ( ?population > 60000 ).
    filter ( !contains(?label, ",") ).
}
"""

import json
import re

cities = {}

print("Loading cities...")

with open("modules/tables/cities.json") as file:
   point_re = re.compile(r"Point\((?P<lon>\S+) (?P<lat>\S+)\)")
   def point(text):
      match = point_re.match(text)
      return (float(match.group('lon')), float(match.group('lat')))

   for row in json.load(file):
      key = (row['label'].lower(), row['lang'])
      if key not in cities or int(row['population']) > cities[key][1]:
         cities[key] = point(row['coords']), int(row['population'])

# Remove population
for key in cities: cities[key] = cities[key][0]

print("Cities loaded.")


def get(cityname, language='en'):
   try: return cities[(cityname.lower(), language.lower())]
   except: return None

def contained(text, language='en'):
   text = text.lower()
   candidates = []

   for city, lang in cities:
      if lang == language and city in text and re.search(r"\b%s\b" % re.escape(city), text):
         candidates.append((city, cities[(city, lang)]))

   return candidates
