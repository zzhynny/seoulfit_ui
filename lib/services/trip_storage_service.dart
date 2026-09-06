import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class SavedTrip {
  final String title;
  final String date;
  final List<String> sourceLinks;

  const SavedTrip({
    required this.title,
    required this.date,
    required this.sourceLinks,
  });

  Map<String, dynamic> toJson() => {
        'title': title,
        'date': date,
        'sourceLinks': sourceLinks,
      };

  factory SavedTrip.fromJson(Map<String, dynamic> json) => SavedTrip(
        title: json['title'] as String? ?? '',
        date: json['date'] as String? ?? '',
        sourceLinks: (json['sourceLinks'] as List?)?.cast<String>() ?? [],
      );
}

class TripStorageService {
  static const _key = 'saved_trips';

  static Future<void> saveTrip(
      String title, String date, List<String> sourceLinks) async {
    final prefs = await SharedPreferences.getInstance();
    final existing = await getTrips();
    final updated = [
      SavedTrip(title: title, date: date, sourceLinks: sourceLinks),
      ...existing,
    ];
    final encoded = updated.map((t) => jsonEncode(t.toJson())).toList();
    await prefs.setStringList(_key, encoded);
  }

  static Future<List<SavedTrip>> getTrips() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_key) ?? [];
    return raw
        .map((s) => SavedTrip.fromJson(
            jsonDecode(s) as Map<String, dynamic>))
        .toList();
  }
}
