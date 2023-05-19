#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
where.py - Miscellaneous geolocating services

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

import GeoIP
import geopy, geopy.distance
import geocoder
import reverse_geocode
import re
from obspy import geodetics
import geojson
import overpass
import mobile_codes
from obspy.geodetics import FlinnEngdahl
from time import time
from itertools import chain
from ipaddress import ip_address
from threading import Thread, Event
import countrynames
from cachetools import LFUCache
from timezonefinder import TimezoneFinder

from modules import utils
# The following module isn't available as it's hard to isolate from the rest of unrelated bot code.
# This module should still work without it by falling back with an "except" clause.
# from modules import engines
from modules.timing import Balancer, Stopwatch, profile
from modules.tables import cities

geoipv4 = GeoIP.open("/usr/share/GeoIP/GeoIPCity.dat", GeoIP.GEOIP_STANDARD)
geoipv6 = GeoIP.open("/usr/share/GeoIP/GeoLiteCityv6.dat", GeoIP.GEOIP_STANDARD)
regions = FlinnEngdahl()


services = ['nominatim', 'photon', 'opencage', 'geonames']
timestamps = {service: 0 for service in services}
params = {
   'nominatim': ({}, {'language': None, 'addressdetails': True, 'geometry': 'geojson'}, {'language': None}),
   'photon': ({}, {'language': None}, {'language': None}),
   'opencage': ({'api_key': "-------"}, {'language': None}, {'language': None}),
   'geocodefarm': ({}, {}, {}),
   'geonames': ({'username': 'my-name'}, {}, {}),
   'yandex': ({}, {}, {}),
   'arcgis': ({}, {}, {}),
   'liveaddress': ({'auth_id': "------", 'auth_token': "-------"}, {}, {}),
   'cities': ({}, {}, {}),
}


class OSM(object):
   endpoints = [
      'https://overpass-api.de/api/interpreter',
      'https://lz4.overpass-api.de/api/interpreter',
      'https://z.overpass-api.de/api/interpreter',
#      'http://overpass.openstreetmap.fr/api/interpreter',
#      'https://overpass.openstreetmap.ru/api/interpreter'
      'https://overpass.kumi.systems/api/interpreter',
#      'https://overpass.nchc.org.tw/api/interpreter',
   ]

   endpoints = Balancer(endpoints)
   cache = LFUCache(maxsize=128)

   def __new__(cls, query, timeout=30, format='geojson'):
      try:
         entry = cls.cache[query, format]
         if entry and entry['event'].wait(timeout=timeout):
            utils.log("Overpass query gotten from cache: %r" % query)
            if entry['output']: return entry['output']
      except: pass

      try:
         entry = cls.cache[query, format] = {'event': Event(), 'output': None}

         for count in range(3):
            with cls.endpoints(timeout=timeout, roundrobin=True) as endpoint:
               try:
                  utils.log("Running OSM query at %r: %r (timeout %r)" % (endpoint, query, timeout))
                  entry['output'] = overpass.API(endpoint=endpoint, timeout=timeout).Get(query, responseformat=format)
                  entry['event'].set()
                  return entry['output']
               except overpass.errors.TimeoutError as error: raise error
               except Exception as error:
                  utils.error("Overpass messup on %r" % endpoint)
                  raise error
         else: raise RuntimeError("No Overpass server could heed the request")
      except:
         del cls.cache[query, format]


class Coords(utils.Commutative):
   def __hash__(self):
      return hash((round(self.latitude, 2), round(self.longitude, 2), round(self.altitude, 1)))

   def __eq__(self, other):
      if abs(self.lat-other.lat) > 0.001: return False
      if abs(self.lon-other.lon) > 0.001: return False
      if abs(self.alt-other.alt) > 0.01: return False
      if abs(self.confidence-other.confidence) > 0.05: return False
      if abs(self.radius-other.radius) > 0.5: return False

      return True

   def __sub__(self, other):
      try:    distance = geodetics.base.gps2dist_azimuth(self.lat, self.lon, other.lat, other.lon)[0] / 1000.0
      except: distance = geopy.distance.distance(self.point, other.point).km

      return distance + max(distance*0.5, (self.radius + other.radius)*0.25)

   def __add__(self, other):
      return Coords(point=(self.lat + other.lat, self.lon + other.lon, self.alt + other.alt), radius=(self.radius + other.radius))

   def __mul__(self, other):
      return (self.lat*other, self.lon*other, self.alt*other)

   def __div__(self, other):
      return (self.lat/other, self.lon/other, self.alt/other)

   def __repr__(self):
      return "Coords({coords.lat:.3f}, {coords.lon:.3f}, {coords.alt} km, radius={coords.radius:.2f} km, confidence={coords.confidence:.2f})".format(coords=self)

   def __unicode__(self):
      output = "({lat}, {lon})".format(lat=round(self.latitude, 3), lon=round(self.longitude, 3))
#      placename = geonames_reverse(self).address    # gets printed where it shouldn't, made a @property placename instead

      if self.radius > 1.0:      output += u" ± {radius} km".format(radius=int(self.radius))
#      if placename:              output += u" ~ {place}".format(place=placename)
      if self.altitude > +1:     output += u", {type}{alt} km".format(type=u"↑", alt=abs(int(self.altitude)))
      if self.altitude < -1:     output += u", {type}{alt} km".format(type=u"↓", alt=abs(int(self.altitude)))
      if self.confidence < 0.7:  output += u" ({conf}%)".format(conf=int(self.confidence*100))

      return output

   __str__ = __unicode__

   def __format__(self, style):
      if style == 'uri':
         return "geo:{coords.lat},{coords.lon},{coords.alt}".format(coords=self)
      else:
         return unicode(self)

   @staticmethod
   def normalize(coords):
      cardinals = {
         'N': ('North', 'NORTH', 'degrees north', 'LU'),
         'S': ('South', 'SOUTH', 'degrees south', 'LS'),
         'W': ('West', 'WEST', 'degrees west', 'BB'),
         'E': ('East', 'EAST', 'degrees east', 'BT'),
         '': ('(', ')'),
      }

      for cardinal, terms in cardinals.items():
         for term in terms: coords = coords.replace(term, cardinal)

      return coords

   @property
   def placename(self):
      return geonames_reverse(self).address

   def __init__(self, point, radius=None, confidence=None):
      self.radius = 0.0
      self.confidence = 1.0

      if isinstance(point, type(self)):
         self.point = point.point
         self.radius = radius or point.radius
         self.confidence = confidence or point.confidence
      else:
         try: self.point = geopy.point.Point(self.normalize(point))
         except: self.point = geopy.point.Point(point)

      self.radius = radius or self.radius
      self.confidence = (confidence or self.confidence) if self.point else 0.0

   @classmethod
   def fromgeojson(cls, coords):
      try: coords = coords['coordinates'] if coords['type'] == 'Point' else coords
      except: pass

      return cls(point=(coords[1], coords[0], (coords[2] if 2 in coords else 0)))

   @classmethod
   def fromgeometry(cls, geometry):
      try:
         nodes = [geometry.coordinates] if geometry.type == 'Point' else chain(*geometry.coordinates) if geometry.type == 'Polygon' else geometry.coordinates
      except:
         nodes = [geometry['coordinates']] if geometry['type'] == 'Point' else chain(*geometry['coordinates']) if geometry['type'] == 'Polygon' else geometry['coordinates']

      return [cls.fromgeojson(coords) for coords in nodes]

   @classmethod
   def center(cls, points):
      def mean(items):
         values, weights = zip(*items)
         return sum(value*weight for value, weight in zip(values, weights)) / sum(weights)

      points = [point if type(point) is tuple else (point, 1.0) for point in points]

      if points:
         coords = Coords((mean((p.lat, w) for p, w in points), mean((p.lon, w) for p, w in points), mean((p.alt, w) for p, w in points)))
         coords.radius = round(2.0*mean(((p - coords)**2.0, w) for p, w in points)**0.5, 5)

         return coords

   @property
   def latitude(self): return self.point.latitude

   @property
   def longitude(self): return self.point.longitude

   @property
   def altitude(self): return self.point.altitude

   def round(self, digits=2):
      rounded = type(self)((round(self.lat, digits), round(self.lon, digits), round(self.alt, digits)))
      rounded.radius = max(rounded.radius, rounded - self)
      return rounded

   lat, lon, alt = latitude, longitude, altitude


def geocode_old(entity, language='en', reverse=False):
   global services, parameters, timestamps, failures

   started = time()

   for service in services[:2]:
      for n in [1, 2]:
         params[service][n]['exactly_one'] = True
         params[service][n]['timeout'] = 1
         if 'language' in params[service][n]: params[service][n]['language'] = language

      try:
         credentials, options = params[service][0], params[service][1 if not reverse else 2]
         geocoder = geopy.get_geocoder_for_service(service)(**credentials)
         location = geocoder.reverse(entity.point, **options) if reverse else geocoder.geocode(entity, **options)
         timestamps[service] = time()
         if location and location.address and location.point: return location
      except Exception as error:
         utils.log("Geocoder error using %s (%s)" % (service, error))
         services.remove(service); services.append(service)
         timestamps[service] = time() + max(600, (time() - timestamps[service])*2)

      if time() - started > 2.0: break

   try:
      if reverse: return geopy.Location(address=region(entity).title(), point=entity.point)
      if not reverse: return geopy.Location(address=entity, point=city(entity)) if city(entity) else None
   except: utils.error("Geolocation failed")

   return None


@utils.cache(256)
@profile
def geocode(entity, language='en', reverse=False, timeout=10, tolerance=100.0):
   def determine(entity):
      methods = [
         ('geocode', 1.2, geocode.geoip, lambda entity: str(ip_address(unicode(entity)))),
         ('reverse', 1.0, geocode.reverse, lambda entity: (entity.latitude, entity.longitude)),
         ('geocode', 2.5, geocode.direct, lambda entity: unicode(entity)),
      ]

      for method, threshold, geocoders, transform in methods:
         try: return method, threshold, transform(entity), geocoders(timeout=timeout, attempts=4, roundrobin=True)
         except: continue

      raise RuntimeError("No way to resolve location {entity} of type {type}".format(entity=entity,type=type(entity)))

   def bogus(result):
      if not result.ok or tuple(result.latlng) == (0, 0):
         return True
      else:
         keys = ('quality', 'type', 'osm_value', 'osm_type')
         types = [result.json.get(key) for key in keys]
         return 'continent' in types or 'country' in types or countrynames.to_code(result.location)

   try:
      if not sea(entity): return geonames_reverse(entity)
   except:
      utils.log("Couldn't return quickly from geonames for entity %r" % entity)

   method, threshold, entity, geocoders = determine(entity)
   candidates = []

   while threshold < 5:
      utils.log("Trying to geocode with load balancer at threshold {t}".format(t=threshold))

      try:
         with geocoders as service:
            result = geocoder.get(
               entity,
               provider=service,
               timeout=2,
               method=method,
               session=geocode.session,
               lang=language,
               lang_code=language,
               **geocode.credentials.get(service, {})
            )
            if result.error: raise RuntimeError(result.error)

      except Balancer.Exhausted:
         utils.log("Balancer gave up on {entity}".format(entity=entity))
         break
      except: continue

      if bogus(result):
         threshold += threshold*0.2
         continue

      result.coords = Coords(result.latlng)
      result.point = result.coords.point
      candidates.append(result)
      geocode.working.add(service)

      try:
         result.extreme1 = Coords(result.json['bbox'].get('southeast') or result.json['bbox'].get('southwest'))
         result.extreme2 = Coords(result.json['bbox'].get('northeast') or result.json['bbox'].get('northwest'))
         if result.extreme1 - result.extreme2 < tolerance*2: result.coords.radius = (result.extreme1 - result.extreme2) * 0.5
      except:
         result.extreme1 = result.extreme2 = result.coords

      if candidates:
         consistent = {c1 for c1 in candidates for c2 in candidates if c1 is not c2 and c1.coords - c2.coords < tolerance}

         if len(consistent) * 1.0 - (len(candidates) - len(consistent)) * 0.1 >= threshold:
#         if sum(1 if (other.coords - first.coords < 50.0) else -0.1 for other in candidates) >= threshold:
            result = sorted(consistent, key=lambda result: result.confidence, reverse=True)[0]
            if all(candidate.coords - result.coords < tolerance*2 for candidate in consistent):
               result.coords = Coords.center(place.coords for place in consistent)
               result.coords.confidence = max(0.0, 1.0 - result.coords.radius/tolerance)
               result.point = geopy.point.Point((result.coords.lat, result.coords.lon))

               utils.log("Working geocoders: {geocoders}".format(geocoders=", ".join(geocode.working)))

               if result.coords.radius > 300:
                  utils.log("Radius for '{name}' is {radius:.0f} with candidates: {candidates}".format(name=entity, radius=result.coords.radius, candidates=candidates))

               return result
            else:
               distances = sorted({c1.coords - c2.coords for c1 in candidates for c2 in candidates if c1 is not c2})
               utils.log("{entity} might be resolved to multiple locations {results}, distances: {distances}".format(entity=entity, results=consistent, distances=distances))
               break

   if method == 'reverse':
      result.coords = Coords(entity)
      result.point = result.coords.point
#      if not sea(result.coords): return geonames_reverse(entity)
      result.address = region(result.coords).title()
      result.add("Resolved by Flinn-Engdahl region")
#      if result.address: return result     # This should work but it's (parly?) done already by alert.py and it causes weird error, perhaps due to double geocoding: the South Sandwich Islands region ended up being in "Southwest, Czechia"
   elif method == 'geocode':
      utils.log("Locating location based on city: %r" % entity)
      result.coords = city(entity)
      result.point = result.coords.point if result.coords else None
      result.address = entity
      result.add("Resolved by city name match")
      if result.coords: return result

   utils.log("{entity} could NOT be convincingly resolved by {services}, with {time} seconds left".format(entity=entity, time=geocoders.timeout, services=[r.provider for r in candidates]))
   raise RuntimeError("Location cannot be geocoded")


geocode.blacklist = {'google', 'w3w', 'mapzen', 'canadapost', 'here', 'tamu', 'tomtom', 'bing', 'baidu', 'gaode', 'mapquest', 'gisgraphy', 'ottawa', 'uscensus'}
geocode.geoip = {'ipinfo', 'freegeoip', 'maxmind'}
geocode.direct = {service for service in geocoder.api.options if 'geocode' in geocoder.api.options[service]}
geocode.reverse = {service for service in geocoder.api.options if 'reverse' in geocoder.api.options[service]}
geocode.direct = Balancer(geocode.direct - geocode.blacklist - geocode.geoip)
geocode.reverse = Balancer(geocode.reverse - geocode.blacklist - geocode.geoip)
geocode.geoip = Balancer(geocode.geoip - geocode.blacklist)
geocode.session = geocoder.base.requests.Session()
geocode.credentials = {}
geocode.working = set()


@utils.cache(64)
def city(text, language='en'):
   candidate = None
   length = 0
   count = 0
   words = [word.strip(".#?! ") for word in re.split(u".#?!'’ ", text)]

   with Stopwatch("Lexical analysis for %r" % text, long=0.5):
      # Exclude major languages that are known not to inflect for case, for speed
      if language not in ['en', 'it', 'es', 'fr', 'tl', 'zh', 'ja']:
         try:
            regex = re.compile(r"[^/]*/\*?(?P<lexeme>[^<]*).*")
            analysis = engines.Analyzer(u" ".join(words)).process(language).output[0][0]
            words = [regex.match(expansion).group('lexeme') for expansion, term in analysis]
            print("Words are now: '%s'" % " ".join(words))
         except:
            utils.log("WARNING: Couldn't lexically analyze words in language %r" % language)

   for lang in [language, 'en']:
      for word in words:
         coordinates = cities.get(word, lang)
         if coordinates:
            count += 1
            if len(word) > length:
               candidate = coordinates
               length = len(word)
               print("Found city: '%r' from '%r'" % (word, text))

      if candidate: break
      else: count += 1

   else: return None

   return Coords(Coords.fromgeojson(candidate), confidence=0.7/count)  # was 0.5 but increased to provide Kiev sirens with more coverage

@utils.cache(64)
def region(coords):
   return regions.get_region(coords.longitude, coords.latitude)

def languages(region):
   mapping = [
      ('Adriatic Sea', ['en', 'it']),
      ('Aegean Sea', ['el', 'tr', 'en']),
      ('Ionian Sea', ['el', 'en', 'it']),
      ('Aleutian', ['en', 'ru']),
      ('Argentina', ['es']),
      ('Arizona-Sonora', ['en', 'es']),
      ('Bering Sea', ['en', 'ru']),
      ('Peru-Brazil', ['es', 'pt']),
      ('Brazil', ['pt']),
      ('New Brunswick, Canada', ['en', 'fr']),
      ('Quebec, Canada', ['fr', 'en']),
      ('California', ['en', 'es']),
      ('Celebes Sea', ['in', 'ceb']),
      ('Ceram Sea', ['in']),
      ('Costa Rica', ['es']),
      ('Crimea', ['uk', 'ru']),
      ('New Mexico-Chihuahua', ['en', 'es']),
      ('New Mexico', ['en']),
      ('Texas-Mexico', ['en', 'es']),
      ('Mexico', ['es']),
      ('Guatemala', ['es']),
      ('Honduras', ['es']),
      ('Salvador', ['es']),
      ('Nicaragua', ['es']),
      ('California-Baja California', ['en', 'es']),
      ('China', ['zh']),
      ('Eastern Russia-Northeastern China', ['zh', 'ru']),
      ('Chile', ['es']),
      ('Costa Rica', ['es']),
      ('Cyprus', ['el', 'tr']),
      ('Dodecanese Islands', ['el', 'tr']),
      ('Georgia-Armenia-Turkey', ['tr', 'hy', 'ka']),
      ('Greece-Albania', ['el', 'sq']),
      ('Greece-Bulgaria', ['el', 'bg']),
      ('Greece', ['el']),
      ('Japan', ['ja']),
      ('Kamchatka', ['ru']),
      ('Korea', ['ko']),
      ('Kuril Islands', ['ja', 'ru']),
      ('Iceland', ['is']),
      ('Indonesia', ['id']),
      ('India-Bangladesh', ['hi', 'bn']),
      ('India-Nepal', ['hi', 'ne']),
      ('Southern Indiana', ['en']), # This is needed because of the following one being a match for it
      ('Southern India', ['en', 'te', 'ta', 'ka', 'ml']),
      ('Italy', ['it']),
      ('Laos', ['lo', 'th']),
      ('Molucca', ['in']),
      ('Mona Passage', ['es']),
      ('Myanmar-India', ['hi', 'my', 'be', 'en']),
      ('Komandorsky', ['ru']),
      ('Cebu, Philippines', ['ceb', 'tl']),
      ('Mindanao, Philippines', ['ceb', 'tl']),
      ('Davao, Philippines', ['ceb', 'tl']),
      ('Leyte, Philippines', ['ceb', 'tl']),
      ('Samar, Philippines', ['ceb', 'tl']),
      ('Negros, Philippines', ['ceb', 'tl']),
      ('Philippines', ['tl']),
      ('Puerto Rico', ['es', 'en']),
      ('Pyrenees', ['es', 'fr', 'ca', 'eu']),
      ('Russia', ['ru']),
      ('Ryukyu', ['ja', 'ru']),
      ('Turkey', ['tr']),
      ('Yellow Sea', ['zh', 'ko']),
   ]

   for subregion, languages in mapping:
      if subregion.lower() in region.lower(): return languages


def geonames_reverse(entity):
   coordinates = (entity.lat, entity.lon) if type(entity) is Coords else tuple(entity)
   result = reverse_geocode.get(coordinates)
   result = {name: value.decode('utf-8') for name, value in result.items()}
   location = geocoder.location(coordinates)
   location.json = result
   location.address = u"{result[city]}, {result[country]}".format(result=result)
   return location


@profile
def locate(entity, language='en', quick=False):
   if not entity: return None

   if quick:
      try: return geonames_reverse(entity)
      except: utils.error("Cannot quickly get reverse location of %r" % entity)

   try: return geocode(Coords(entity), language=language) or None
   except: pass

   try: return geocode(entity, language=language) or None
   except: pass

   return None


class Address(object):
   def __init__(self, location):
      self.address = location.address
      self.dictionary = location.json
#      self.dictionary = self.get('address', 'properties', 'components', 'address_components', type=dict) or self.dictionary

      if isinstance(self.dictionary, list):
         self.dictionary = {entry['types'][0]: (entry['long_name'], entry['short_name']) for entry in self.dictionary}
         self.dictionary['country'], self.dictionary['country_code'] = self.dictionary.get('country', (None, None))
         self.dictionary['region'], self.dictionary['region_code'] = self.dictionary.get('administrative_area_level_1', (None, None))
         self.dictionary['province'], self.dictionary['province_code'] = self.dictionary.get('administrative_area_level_2', (None, None))
         self.dictionary['city'], self.dictionary['city_code'] = self.dictionary.get('administrative_area_level_3', (None, None))
         self.dictionary['suburb'], self.dictionary['suburb_code'] = self.dictionary.get('locality', (None, None))

      self.street = self.get('street', 'road')
      self.postcode = self.get('postal', 'postcode')
      self.locality = self.get('suburb', 'locality', 'sublocality')
      self.city = self.get('city', 'town', 'village', 'name', 'toponymName', 'admin_3')
      self.province = self.get('county', 'province', 'adminName2', 'admin_2')
      self.region = self.get('state', 'region', 'adminName1', 'admin_1')
      self.country = self.get('country_long', 'countryName', 'country')

      self.country = self.country or self.get('country_code', 'countryCode')
      self.countrycode = (self.get('country_code', 'countryCode') or countrynames.to_code(self.country) or "??").upper()


   def get(self, *keys, **kwargs):
      if not self.dictionary: return None
      cls = kwargs.get('type', object)
      for key in keys:
         if self.dictionary.get(key) and isinstance(self.dictionary.get(key), cls): return self.dictionary[key]

   def tostring(self, format='long'):
      try: locale = min(filter(None, [self.province, self.city, self.region]), key=len)
      except: locale = None

      try:
         _, _, shortname = self.country.partition(" of ")
         shortname = shortname or (self.country if len(self.country) < 25 else self.countrycode)
      except:
         shortname = self.countrycode if self.countrycode != "??" else None

      result = {
         'human': [(self.city or self.province or self.locality or self.region or shortname)],
         'short': [locale, shortname],
         'fixed': [self.city, self.province, self.region, self.country],
         'long': [self.locality, self.city, self.province, self.region, self.country],
         'machine': [self.street, self.postcode, self.locality, self.city, self.province, self.region, self.country],
      }[format]

      print result

      return u', '.join(filter(None, result)) or self.address

   def __str__(self):
      return self.tostring('machine')


@utils.cache(128)
@profile
def sea(coords):
   seas = {
      'OFF COAST ',
      ' OCEAN'
   }
   lands = {
      'AFGHANISTAN',
      'AUSTRIA',
      'BOLIVIA',
      'CENTRAL AFRICA',
      'CHAD REGION',
      'CHIHUAHUA',
      'COLORADO',
      'CZECH AND SLOVAK',
      'GANSU, CHINA',
      'HUNGARY',
      'IDAHO',
      'KANSAS',
      'KASHMIR',
      'CENTRAL KAZAKHSTAN',
      'EASTERN KAZAKHSTAN',
      'SOUTHEASTERN KAZAKHSTAN',
      'KYRGYZSTAN',
      'NEBRASKA',
      'NIGER',
      'MALI',
      'MISSOURI',
      'MONGOLIA',
      'MONTANA',
      'NEPAL',
      'NEVADA',
      'OKLAHOMA',
      'PARAGUAY',
      'QINGHAI',
      'SICHUAN',
      'SOUTHWESTERN SIBERIA',
      'SWITZERLAND',
      'TAJIKISTAN',
      'TENNESSEE',
      'UZBEKISTAN',
      'WEST VIRGINIA',
      'WYOMING',
      'XINJIANG',
      'YUNNAN',
      'ZAMBIA'
   }

   if any(term in region(coords) for term in seas): return True
   if any(term in region(coords) for term in lands): return False

   query = 'is_in(%s,%s); area._[admin_level!=2][boundary!=maritime][place!=sea];'
   result = OSM(query % (coords.lat, coords.lon), format='csv(::id; false)', timeout=5)

   return not result


@utils.cache(512)
@profile
def osm(coords=None, radius=10, timeout=60, sort=None, **tags):
   radius = 1000*radius

   query = [('["{key}"]' if type(tags[key]) is type else '["{key}"~"^{value}$"]').format(key=key, value=tags[key]) for key in tags if key]
   query = ''.join(query) + ("(around:{radius},{coords.lat},{coords.lon})" if radius and coords else "").format(radius=radius, coords=coords)

   utils.log("Running Overpass query {query}".format(query=query))

   for scheme in ["node{0}; out; way{0};", "node{0};", "way{0};"]:
      try:
         features = OSM(scheme.format(query), timeout=timeout).features
         if features: break
      except:
         utils.error("Overpass query failed")

   # Prune and convert fields that look like numbers if they are output fields (not assigned a value in the query)
   transforms = [(lambda value: value), (lambda value: str(value).strip(" ~").replace(",", "")), (lambda value: None)]

   for index, feature in enumerate(features):
      feature.properties['distance'] = min(node - coords for node in Coords.fromgeometry(feature.geometry))

      for key in tags:
         if type(tags[key]) is type:
           for transform in transforms:
              try:
                 feature.properties[key] = tags[key](transform(feature.properties[key]))
                 break
              except:
                 continue
           else: features[index] = None

   features = filter(None, features)

   utils.log("Completing Overpass query {query}".format(query=query))

   return sorted(features, key=sort or (lambda feature: feature.properties['distance'])) if coords else features


@utils.cache(64)
def webcams(coords, radius=10, live=True):
   if not coords: return []

   live = "property=live" if live else ""
   url = "https://api.windy.com/api/webcams/v2/list/nearby=%s,%s,%s/orderby=distance/%s?show=webcams:url"
   output = utils.web.get(url % (coords.lat, coords.lon, radius, live), headers={'X-Windy-Key': windy_key})

   webcams = output.json()['result']['webcams']
   webcams = [(webcam['url']['current'], webcam['title']) for webcam in webcams]
   webcams = [(link['mobile'] or link['desktop'], title) for link, title in webcams]

   if live: webcams = [(link.split("-")[0].replace("/webcam/", "/webcam/stream/"), title) for link, title in webcams]

   return webcams

@utils.cache(64)
def cells(coords):
   url = "http://opencellid.org/cell/getInArea"

   bbox = "%s,%s,%s,%s" % (coords.latitude-0.03, coords.longitude-0.03, coords.latitude+0.03, coords.longitude+0.03)
   print bbox
   cells = utils.web.get(url, params={'key': opencellid_key, 'BBOX': bbox ,'format': 'json', 'limit': 100}).json()
   print cells #[:256]
   cells = cells['cells']

   services = {}
   for cell in cells:
      try:
         operator = mobile_codes.mcc_mnc(str(cell['mcc']), str(cell['mnc']))
         services[operator] = services.get(operator, set()) + cell['radio']
      except KeyError:
         utils.log("No known operator with MCC %s and MNC %s" % (cell['mcc'], cell['mnc']))

   return services


def timezone(coords):
   return TimezoneFinder().timezone_at(lat=coords.latitude, lng=coords.longitude)


def setup(bot):
   utils.log("Registering credentials")
   geocode.credentials = bot.config.credentials.get('geocoders', {})

   def train():
      for place in setup.testplaces:
         if not geocode(place): utils.log("WARNING: Could not resolve {place}".format(place=place))

   Thread(target=train).start()

setup.testplaces = ["Los Angeles", "Istanbul", "New Delhi", "Tokyo", Coords((40, -76)), Coords((42, 12))]
