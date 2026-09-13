/// Saves the trip's journey stamp for the traveller to keep: into the photo
/// library on a phone, as a browser download on web (gal has no web support).
library;

export 'stamp_saver_io.dart' if (dart.library.js_interop) 'stamp_saver_web.dart';
