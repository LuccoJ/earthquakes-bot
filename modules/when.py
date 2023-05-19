#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
when.py - Timekeeping module

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

import re
import maya
import pytz
import parsedatetime


def offset(hours=0):
   return pytz.FixedOffset(hours*60.0)

class When(maya.MayaDT):
   def __format__(self, style):
      style, _, timezone = style.partition("@")
      #target = self if not timezone else self.datetime().to(timezone)
      target = self

      if style == 'short':   return '{:%H:%M %Z}'.format(target)
      if style == 'fixed':   return '{:%Y-%m-%d %H:%M:%S %Z}'.format(target)
      if style == 'machine': return target.subtract(microseconds=self.microsecond).iso8601()
      if style == 'long':    return '{human} ({exact:%H:%M:%S %Z})'.format(human=self.slang_time(), exact=target)
      if style == 'human':   return self.slang_time()

      return super(When, self).__format__(style)

   @classmethod
   def fromstring(cls, time, fuzzy=False, timezone='UTC'):
      def multiformat(time, timezone=None, prefer_dates_from='past'):
         candidates = []

         for dayfirst, yearfirst in ((False, False), (False, True), (True, False), (True, True)):
            candidates.append(maya.parse(time, timezone=timezone, day_first=dayfirst, year_first=yearfirst))

         if prefer_dates_from == 'past':
            return max(candidate for candidate in candidates if candidate < maya.now())
         elif prefer_dates_from == 'future':
            return min(candidate for candidate in candidates if candidate > maya.now())
         elif prefer_dates_from == 'current':
            return min(candidate for candidate in candidates if maya.now().add(days=1) > candidate > maya.now().subtract(days=1))
         else:
            return max(candidates)

      if not time: return

      orig = time

      try: time = ' '.join(unicode(time).strip().split())
      except: pass

      try: return cls(float(time)/1000.0 if float(time) > maya.now().add(years=1000).epoch else float(time))
      except: pass

      parsers = [multiformat, maya.when, maya.parse, maya.MayaDT.from_iso8601, maya.MayaDT.from_rfc3339, maya.MayaDT.from_rfc2822]
      parameters = [{'timezone': timezone, 'prefer_dates_from': fuzzy or 'current'}, {'timezone': timezone}, {}]

      for kwargs in parameters:
         for parser in parsers:
            try: return cls(parser(time, **kwargs).epoch)
            except: pass

      if fuzzy:
         time = str(re.sub(u"[^\s\w:/.,'-時分秒]+", ":", time.replace(" - ", " ").replace(timezone, " ")))
         best = None
         for locale in ['en_GB', 'en_US']:
            try: parsed, flag, start, end, match = parsedatetime.Calendar(constants=parsedatetime.Constants(localeID=locale)).nlp(time)[0]
            except: parsed = False

            if parsed:
               best = parsed
               if flag == 3: break

         return cls.from_datetime(best) if best else None

      raise ValueError("No module could parse time string %r, timezone %r" % (orig, timezone))

   @classmethod
   def now(cls):
      return cls(maya.now().epoch)
