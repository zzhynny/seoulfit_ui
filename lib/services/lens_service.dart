import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../config/api_base.dart';
import '../models/landmark_analysis.dart';

class LensService {
  static String get _base => apiBase;

  Future<LandmarkAnalysis> analyze(Uint8List bytes, String filename) async {
    final uri = Uri.parse('$_base/analyze-landmark');
    final mime = _guessMimeType(filename);
    final parts = mime.split('/');

    final request = http.MultipartRequest('POST', uri)
      ..files.add(
        http.MultipartFile.fromBytes(
          'file',
          bytes,
          filename: filename.isNotEmpty ? filename : 'capture.jpg',
          contentType: MediaType(parts[0], parts[1]),
        ),
      );

    final streamed =
        await request.send().timeout(const Duration(seconds: 60));
    final response = await http.Response.fromStream(streamed);

    if (response.statusCode != 200) {
      throw Exception(
        'Backend returned ${response.statusCode}: ${response.body}',
      );
    }

    final payload =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return LandmarkAnalysis.fromJson(payload);
  }

  String _guessMimeType(String filename) {
    final lower = filename.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.gif')) return 'image/gif';
    if (lower.endsWith('.heic') || lower.endsWith('.heif')) return 'image/heic';
    return 'image/jpeg';
  }
}
