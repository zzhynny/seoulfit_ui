import 'dart:typed_data';

import 'package:image_picker/image_picker.dart';

import '../../models/landmark_analysis.dart';
import '../../models/lens.dart';
import '../../services/lens_service.dart';
import '../repositories/lens_repository.dart';

/// [LensRepository] backed by POST /analyze-landmark.
class ApiLensRepository implements LensRepository {
  ApiLensRepository({LensService? service, ImagePicker? picker})
      : _service = service ?? LensService(),
        _picker = picker ?? ImagePicker();

  final LensService _service;
  final ImagePicker _picker;

  @override
  Future<LensPlaceResult?> scanPlace(LensPhotoSource source) async {
    final file = await _picker.pickImage(
      source: source == LensPhotoSource.camera
          ? ImageSource.camera
          : ImageSource.gallery,
      // The backend downscales anyway and the upload is a multipart POST over
      // hotel wifi; a full 12MP capture just makes the traveller wait.
      maxWidth: 1600,
      imageQuality: 85,
    );
    if (file == null) return null;

    final bytes = await file.readAsBytes();
    return _toPlaceResult(await _service.analyze(bytes, file.name), bytes);
  }
}

LensPlaceResult _toPlaceResult(LandmarkAnalysis analysis, Uint8List photo) {
  // `public_info_en` is the translated copy of `public_info` and is empty when
  // the photo matched no row in seoul.json. Falling back to the Korean keeps
  // the fields populated rather than blanking the card.
  final info = analysis.publicInfoEn.isNotEmpty
      ? analysis.publicInfoEn
      : analysis.publicInfo;

  String field(String key) => (info[key] ?? '').trim();

  return LensPlaceResult(
    name: analysis.nameEnglish,
    address: field('address'),
    confidence: analysis.confidence,
    hours: field('hours'),
    openDays: field('open_days'),
    closedNote: field('closed_days'),
    gettingThere: field('subway'),
    hashtags: _tags(field('tags')),
    // `description` is already the English narration the backend generates
    // from the translated facts — the audio guide's script, not a summary.
    audioGuideCategory: analysis.category,
    audioGuideTitle: analysis.nameEnglish,
    audioGuideExcerpt: analysis.description,
    photo: photo,
  );
}

/// seoul.json packs tags into one field, variously comma-, hash- or
/// space-separated depending on the row.
List<String> _tags(String raw) {
  if (raw.isEmpty) return const [];
  return raw
      .split(RegExp(r'[,#]'))
      .map((t) => t.trim())
      .where((t) => t.isNotEmpty)
      .toList();
}
