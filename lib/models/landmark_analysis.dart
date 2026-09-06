/// Mirrors the JSON returned by POST /analyze-landmark.
class LandmarkAnalysis {
  final String nameKorean;
  final String nameEnglish;
  final int confidence;
  final String category;
  final String description;
  final bool dataVerified;
  final String dataSource;

  /// Raw Korean fields from seoul.json.
  final Map<String, String> publicInfo;

  /// Same fields translated to English. May be empty if the backend skipped
  /// translation (e.g. no public-data match).
  final Map<String, String> publicInfoEn;

  const LandmarkAnalysis({
    required this.nameKorean,
    required this.nameEnglish,
    required this.confidence,
    required this.category,
    required this.description,
    required this.dataVerified,
    required this.dataSource,
    required this.publicInfo,
    required this.publicInfoEn,
  });

  factory LandmarkAnalysis.fromJson(Map<String, dynamic> json) {
    Map<String, String> coerceMap(Object? raw) {
      if (raw is Map) {
        return raw.map(
          (k, v) => MapEntry(k.toString(), (v ?? '').toString()),
        );
      }
      return <String, String>{};
    }

    return LandmarkAnalysis(
      nameKorean: (json['name_korean'] ?? '').toString(),
      nameEnglish: (json['name_english'] ?? 'Unknown').toString(),
      confidence: (json['confidence'] is int)
          ? json['confidence'] as int
          : int.tryParse('${json['confidence']}') ?? 0,
      category: (json['category'] ?? 'Other').toString(),
      description: (json['description'] ?? '').toString(),
      dataVerified: json['data_verified'] == true,
      dataSource: (json['data_source'] ?? 'none').toString(),
      publicInfo: coerceMap(json['public_info']),
      publicInfoEn: coerceMap(json['public_info_en']),
    );
  }
}
