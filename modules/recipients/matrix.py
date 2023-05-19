"""
matrix.py - Send messages to the Matrix network

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

from modules.recipients import Recipient, Renderer
from modules import utils

from matrix_client.client import MatrixClient


class HTMLRenderer(Renderer):
    def paragraph(self, text): return text

    def autolink(self, link, is_email=False): return link

class Matrix(Recipient):
    protocol = "matrix"
    throttle = 7
    style = 'long'
    bold, italic, colors = "**", "*", False
    renderer = HTMLRenderer()
    priority = 0

    @property
    @utils.cache(32)
    def handle(self):
       try:
          utils.log("MATRIX joining room %r" % self.id)
          utils.log("MATRIX rooms: %r" % len(self.service.get_rooms()))
          return self.service.join_room(self.id)
       except:
          utils.log("MATRIX failed to join room %r, doing direct" % self.id)
          return self.direct(self.id)

    def direct(self, id):
       utils.log("MATRIX rooms: %r" % len(self.service.get_rooms()))

       for room in self.service.get_rooms().values():
          users = room.get_joined_members()
          if len(users) < 2:
             utils.log("MATRIX leaving room %r because it's empty: %r" % (room, users))
             room.leave()
          if len(users) > 2:
             utils.log("MATRIX too many users in room %r, ignoring" % room)
             continue
          if any(user.user_id.lower() == id.lower() for user in users):
             utils.log("MATRIX user found for %r in %s, using room" % (id, room))
             return room

          utils.log("MATRIX user %r not found among %r in %s" % (id, [user.user_id for user in users], room))

       else:
          utils.log("MATRIX user %r not found, creating new room" % id)
          return self.service.create_room(invitees=[id])

    def initialize(self, service, server=None, token=None, password=None, id=None):
       utils.log("Trying to initialize Matrix connection with password...")
       client = MatrixClient(server)
       client.login(id, password, sync=False)

       utils.log("Initialized Matrix.")

       return client

    def submit(self, title, details, coords, tag, pings, urgent=False):
       text = details or title

       return self.handle.send_html(self.renderer(text), body=text, msgtype='m.text' if urgent else 'm.notice')['event_id']

    def redact(self, thread, tag):
       if thread: self.handle.redact_message(thread, reason="See updated statement about {tag}".format(tag=tag))

    @property
    def nickname(self):
       try: return self.handle.get_display_name() or self.handle.user_id
       except: return self.handle.name or self.handle.room_id
