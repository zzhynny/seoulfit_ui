import 'dart:js_interop';

import 'package:http/http.dart' as http;
import 'package:web/web.dart' as web;

/// Downloads the stamp at [url] and hands it to the browser as a file.
///
/// Fetched into a blob first: the backend is a different origin from the web
/// app, and browsers ignore `download` on cross-origin links (they'd just
/// open the image in a tab).
Future<void> saveStampImage(String url) async {
  final response =
      await http.get(Uri.parse(url)).timeout(const Duration(seconds: 20));
  if (response.statusCode != 200) {
    throw Exception('Stamp download failed (${response.statusCode})');
  }
  final blob = web.Blob(
    [response.bodyBytes.toJS].toJS,
    web.BlobPropertyBag(type: 'image/png'),
  );
  final objectUrl = web.URL.createObjectURL(blob);
  web.HTMLAnchorElement()
    ..href = objectUrl
    ..download = 'seoulfit-journey.png'
    ..click();
  web.URL.revokeObjectURL(objectUrl);
}
