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
    this.transitMode,
    this.transitDetail,
    this.exitInstruction,
  });

  final int order;
  final String nameEn;
  final String? nameKo;
  final String arrivalTime;
  final String? transitMode;
  final String? transitDetail;
  final String? exitInstruction;
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
