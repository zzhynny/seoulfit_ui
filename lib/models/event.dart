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
    this.landingUrl,
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

  /// The event's page on the ticket site (`landing_url` from POST /events).
  /// Null on mock data — the card is then inert rather than opening nowhere.
  final String? landingUrl;
}

/// The tab EventsScreen opens on. Musical rather than the first chip: it is
/// the deepest catalogue NOL has, so the grid is never empty on arrival.
const String kDefaultEventCategory = 'Musical';

/// The genre tabs world.nol.com/en/ticket actually has, in its own order and
/// under its own labels — POST /events maps each one to that genre's page.
///
/// This list used to hold six entries, two of them ('Exhibition', 'Theater')
/// names NOL does not use, which left Play&Stay, Sports and Dance with no way
/// into the app at all.
const List<String> kEventCategories = [
  'Play&Stay',
  'Concert',
  'Musical',
  'Play',
  'Exhibitions',
  'Sports',
  'Dance',
  'Classic',
  'Family',
];
