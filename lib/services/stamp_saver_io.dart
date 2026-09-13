import 'package:gal/gal.dart';
import 'package:http/http.dart' as http;

/// Downloads the stamp at [url] and saves it to the photo library. Throws when
/// the download fails or photo access is refused, so the caller can say so.
Future<void> saveStampImage(String url) async {
  final response = await http.get(Uri.parse(url));
  if (response.statusCode != 200) {
    throw Exception('Stamp download failed (${response.statusCode})');
  }
  // Returns true straight away if access was already granted.
  if (!await Gal.requestAccess()) {
    throw Exception('Photo access denied');
  }
  await Gal.putImageBytes(response.bodyBytes, name: 'seoulfit-journey');
}
