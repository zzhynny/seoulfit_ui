import 'package:flutter/material.dart';

class SeoulEvent {
  const SeoulEvent({
    required this.title,
    required this.dateRange,
    required this.venue,
    required this.category,
    required this.posterColors,
    this.posterAsset,
  });

  final String title;
  final String dateRange;
  final String venue;
  final String category;

  /// Gradient colors used as a fallback when [posterAsset] is unset.
  final List<Color> posterColors;

  /// Real poster art, when available.
  final String? posterAsset;
}

const List<String> kEventCategories = [
  'Musical',
  'Concert',
  'Exhibition',
  'Classic',
  'Family',
  'Theater',
];
