// config.js - which kind of site the pages are part of.
//
//   false: served by server.py, which reads the games from this computer.
//   true:  a static site made by tools/make_static.py: plain files that any web
//          server can serve, with each game prepared as a download.
//
// tools/make_static.py writes its own copy of this file with true.
self.KASER_STATIC = false;
