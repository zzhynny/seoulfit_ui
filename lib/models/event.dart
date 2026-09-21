import 'package:flutter/material.dart';

class SeoulEvent {
  const SeoulEvent({
    required this.title,
    this.contentId,
    this.lat,
    this.lng,
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
  /// Null on mock data — the sheet then hides the "View on VisitKorea" button.
  final String? landingUrl;

  /// 한국관광공사 TourAPI's own id (`contentid`). The key POST /event-detail
  /// takes. Null on mock data, which is what makes the card inert there.
  final String? contentId;

  /// Where the event is. Present for every live event (TourAPI fills mapx/mapy
  /// on all 80 Seoul rows), null on mock data — the sheet's map button is
  /// hidden rather than opening a search for nothing.
  final double? lat;
  final double? lng;
}

/// The tab EventsScreen opens on. 'All' rather than a genre: the backend
/// fetches every Seoul event in one pass, so the full grid is the cheap case
/// and each chip is a filter over it, not another round trip.
const String kDefaultEventCategory = 'All';

/// Chips over 한국관광공사 TourAPI's `lclsSystm2` classification, which is what
/// EngService2 actually returns (`cat1`~`cat3` come back empty). The backend
/// owns the label→code map — see `_EV_CHIP` in backend/api.py, and
/// test_events_tourapi.py keeps the two lists from drifting apart.
///
/// These replaced nine ticket-site genre tabs. Seoul has ~79 events across all
/// three chips, so more chips than this leaves most of them nearly empty.
const List<String> kEventCategories = [
  'All',
  'Festivals',
  'Performances',
  'Exhibitions',
];
