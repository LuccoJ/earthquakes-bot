"""
irc.py - Send messages to IRC using the same interface as for "generic" messages

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

from modules.recipients import Recipient

class IRC(Recipient):
    protocol = "irc"
    throttle = 7
    style = 'long'
    bold, italic, underline, colors = "\x02", "\x1d", "\x1f", True
    priority = 0

    def initialize(self, service, bot=None, id=None, password=None):
       return bot

    def submit(self, title, details, coords, tag, pings, urgent=False):
       pings = [ping for ping in pings if not ping.startswith("#") and not ping.startswith("@")]

       self.service.chat.message(None, "", (details or title) + '  ' + ' '.join(pings), target=self.id)

    @property
    def nickname(self):
       return self.id
