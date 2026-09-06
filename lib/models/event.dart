import 'package:flutter/material.dart';

class SeoulEvent {
  const SeoulEvent({
    required this.title,
    required this.dateRange,
    required this.venue,
    required this.category,
    required this.posterColors,
    this.posterAsset,
    this.posterUrl,
  });

  final String title;
  final String dateRange;
  final String venue;
  final String category;

  /// Gradient colors used as a fallback when [posterAsset] is unset.
  final List<Color> posterColors;

  /// Real poster art bundled with the app, when available.
  final String? posterAsset;

  /// Remote poster art (`image_url` from POST /events). Takes precedence over
  /// [posterColors]; [posterAsset] still wins over both so mock builds keep
  /// their Figma artwork.
  final String? posterUrl;
}

const List<String> kEventCategories = [
  'Musical',
  'Concert',
  'Exhibition',
  'Classic',
  'Family',
  'Theater',
];
