/// Category of a single itinerary activity — drives the tag color.
enum ActivityCategory { culture, food, shopping, crafts, teaHouse, nature }

extension ActivityCategoryX on ActivityCategory {
  String get label {
    switch (this) {
      case ActivityCategory.culture:
        return 'Culture';
      case ActivityCategory.food:
        return 'Food';
      case ActivityCategory.shopping:
        return 'Shopping';
      case ActivityCategory.crafts:
        return 'Crafts';
      case ActivityCategory.teaHouse:
        return 'Tea House';
      case ActivityCategory.nature:
        return 'Nature';
    }
  }
}

class TripActivity {
  const TripActivity({
    required this.id,
    required this.time,
    required this.category,
    required this.title,
    required this.description,
    this.imageAsset,
    this.included = true,
    this.visited = false,
    this.aiInsight,
    this.lat,
    this.lng,
    this.poiType = '',
  });

  final String id;
  final String time;
  final ActivityCategory category;
  final String title;
  final String description;
  final String? imageAsset;
  final bool included;
  final bool visited;
  final String? aiInsight;

  /// Coordinates, when this activity came from a real backend POI. Null for
  /// mock data. Final Route draws its map from these.
  final double? lat;
  final double? lng;

  /// The planner's raw `poi_type` (`restaurant`, `cafe`, `history`, …), kept
  /// alongside the coarser [category] because /poi-detail and
  /// /poi-arrival-tip take it to disambiguate a bare name. Empty for mocks.
  final String poiType;

  TripActivity copyWith({bool? included, bool? visited}) => TripActivity(
        id: id,
        time: time,
        category: category,
        title: title,
        description: description,
        imageAsset: imageAsset,
        included: included ?? this.included,
        visited: visited ?? this.visited,
        aiInsight: aiInsight,
        lat: lat,
        lng: lng,
        poiType: poiType,
      );
}

enum MissedReason { notEnoughTime, tooTired, didntFeelLikeIt, other }

class TripDay {
  const TripDay({
    required this.dayNumber,
    required this.date,
    required this.areaName,
    required this.activities,
  });

  final int dayNumber;
  final String date;
  final String areaName;
  final List<TripActivity> activities;

  int get visitedCount => activities.where((a) => a.visited).length;
}

/// The slots the planner collects over chat, shown back on Confirm Slots.
///
/// These are the backend's six `ALL_FIELDS`, not an independent design: what
/// this screen shows has to be what the planner will actually use. The mock's
/// old `duration` field is gone — no backend slot holds it, it's phrasing
/// inside [dateRange] ("Oct 12 for 5 days") — and `region` and `pace`, which
/// the backend does collect, take its place.
class TripPreferences {
  const TripPreferences({
    required this.dateRange,
    required this.region,
    required this.travelStyle,
    required this.groupSize,
    required this.dietaryNotes,
    required this.pace,
  });

  /// `travel_dates` — free text in the user's own phrasing.
  final String dateRange;

  /// `region` — the areas to plan around; drives RAG retrieval.
  final String region;

  /// `category` — what the traveller is here for.
  final String travelStyle;

  /// `companion` — who they're travelling with.
  final String groupSize;

  /// `restrictions` — dietary and accessibility notes.
  final String dietaryNotes;

  /// `pace` — how packed the days should be.
  final String pace;
}

class RouteStop {
  const RouteStop({
    required this.order,
    required this.nameEn,
    this.nameKo,
    required this.arrivalTime,
    this.exitInstruction,
    this.hop,
  });

  final int order;
  final String nameEn;
  final String? nameKo;
  final String arrivalTime;
  final String? exitInstruction;

  /// How to get from this stop to the next one. Null on the last stop of the
  /// trip, and on any pair the planner couldn't route.
  final TransitHop? hop;
}

/// One public-transport option for a hop, from ODsay via the backend.
class TransitChoice {
  const TransitChoice({
    required this.label,
    required this.segments,
    this.totalMinutes,
    this.fareWon,
    this.transfers,
    this.walkMeters,
  });

  /// 'Subway', 'Bus', 'Subway + Bus' — the backend's own `type_label`.
  final String label;

  /// Line-by-line description of the ride, e.g. 'Line 2 → Line 3'.
  final List<String> segments;

  final int? totalMinutes;
  final int? fareWon;
  final int? transfers;
  final int? walkMeters;

  bool get isSubway => label.toLowerCase().contains('subway');
}

/// The leg between two consecutive stops.
class TransitHop {
  const TransitHop({
    required this.options,
    this.distanceKm,
    this.walkMinutes,
    this.carMinutes,
    this.kakaoWalkUrl,
    this.kakaoCarUrl,
  });

  /// Public-transport options, best first.
  ///
  /// Routinely empty: the backend omits them for stops within walking
  /// distance of each other, and ODsay's daily quota being spent produces
  /// the same empty list. Callers must fall back to [walkMinutes] /
  /// [carMinutes] rather than treating this as an error.
  final List<TransitChoice> options;

  final double? distanceKm;
  final int? walkMinutes;
  final int? carMinutes;
  final String? kakaoWalkUrl;
  final String? kakaoCarUrl;

  bool get hasAnything =>
      options.isNotEmpty ||
      walkMinutes != null ||
      carMinutes != null ||
      distanceKm != null;
}

class Itinerary {
  Itinerary({
    required this.preferences,
    required this.days,
    required this.routeStops,
  });

  final TripPreferences preferences;
  final List<TripDay> days;
  final List<RouteStop> routeStops;

  int get stampedDays => days.where((d) => d.visitedCount > 0).length;
}
