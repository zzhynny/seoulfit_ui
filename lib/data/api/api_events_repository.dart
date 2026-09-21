import 'package:flutter/material.dart';

import '../../models/event.dart';
import '../../services/api_service.dart';
import '../repositories/events_repository.dart';

/// [EventsRepository] backed by POST /events, which live-scrapes one ticket
/// genre page per call.
class ApiEventsRepository implements EventsRepository {
  ApiEventsRepository(this._api);

  final ApiService _api;

  @override
  Future<List<SeoulEvent>> fetchEvents(String category) async {
    final rows = await _api.fetchEvents(category);
    return [
      for (var i = 0; i < rows.length; i++) _toEvent(rows[i], category, i),
    ];
  }
}

SeoulEvent _toEvent(Map<String, dynamic> json, String category, int index) {
  String field(String key) => (json[key] ?? '').toString().trim();

  double? coord(String key) {
    final v = json[key];
    return v is num ? v.toDouble() : double.tryParse((v ?? '').toString());
  }

  final url = field('image_url');
  final landing = field('landing_url');
  final cid = field('contentid');
  return SeoulEvent(
    title: field('name'),
    contentId: cid.isEmpty ? null : cid,
    lat: coord('lat'),
    lng: coord('lng'),
    dateRange: field('date'),
    venue: field('venue'),
    // The scraper doesn't label rows — they're all the genre that was asked
    // for, so the chip's own label is the accurate one.
    category: category,
    posterUrl: url.isEmpty ? null : url,
    landingUrl: landing.isEmpty ? null : landing,
    // Only used when the poster is missing or fails to load. Cycling by
    // position keeps a gradient-heavy grid from reading as one flat block.
    posterColors: _fallbackGradients[index % _fallbackGradients.length],
  );
}

/// ponytail: fixed gradient cycle rather than a colour derived from the
/// poster. Sampling the artwork would tie the placeholder to an image that,
/// by definition, hasn't loaded.
const _fallbackGradients = <List<Color>>[
  [Color(0xFF1B1032), Color(0xFFDA4CE0)],
  [Color(0xFFE08A3C), Color(0xFFF2C14E)],
  [Color(0xFF10312B), Color(0xFF4F8A7A)],
  [Color(0xFF2B1B10), Color(0xFFB8654A)],
];
