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
  /// alongside the coarser [category] because /poi-detail takes it to
  /// disambiguate a bare name. Empty for mocks.
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

enum MissedReason {
  notEnoughTime('⏰', 'Not enough time'),
  tooTired('🏃', 'Too tired'),
  didntFeelLikeIt('💭', "Didn't feel like it"),
  other('✏️', 'Other');

  const MissedReason(this.emoji, this.label);

  final String emoji;
  final String label;
}

class TripDay {
  const TripDay({
    required this.dayNumber,
    required this.date,
    required this.areaName,
    required this.activities,
    this.estimatedCost = '',
  });

  final int dayNumber;
  final String date;
  final String areaName;
  final List<TripActivity> activities;

  /// The planner's own cost estimate for the day, already formatted
  /// ("60,000 - 80,000 KRW (approx. \$45-\$60 USD)"). Empty when it didn't
  /// produce one.
  final String estimatedCost;

  int get visitedCount => activities.where((a) => a.visited).length;

  /// Copies the day with new [activities], keeping everything else.
  ///
  /// Rebuilding a TripDay by listing its fields is how estimatedCost got
  /// silently dropped the moment it was added — every caller has to remember
  /// a field it never mentions.
  TripDay withActivities(List<TripActivity> activities) => TripDay(
        dayNumber: dayNumber,
        date: date,
        areaName: areaName,
        activities: activities,
        estimatedCost: estimatedCost,
      );
}

/// A course the planner drew this itinerary from, so the traveller can see
/// where a day came from rather than taking it on trust.
class TripSource {
  const TripSource({
    required this.courseTitle,
    required this.source,
    required this.sourceUrl,
    this.courseId = '',
  });

  final String courseTitle;

  /// Publisher — Visit Seoul, Korea Tourism Organization, and so on.
  final String source;

  final String sourceUrl;
  final String courseId;
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
    this.description = '',
    this.exitInstruction,
    this.hop,
  });

  final int order;
  final String nameEn;
  final String? nameKo;
  final String arrivalTime;

  /// The planner's own note for this stop. Shown immediately under the name and
  /// used as [PoiSummary]'s fallback, so the line is never empty while the
  /// fetched description is in flight. Defaults to '' so the mock repository
  /// (which has no itinerary payload behind it) needs no change.
  final String description;

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
    this.kakaoTransitUrl,
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
  final String? kakaoTransitUrl;

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
    this.summary = '',
    this.sources = const [],
    this.overallScore,
    this.feasibilityScore,
    this.raw = const {},
  });

  final TripPreferences preferences;
  final List<TripDay> days;
  final List<RouteStop> routeStops;

  /// The planner's prose description of the whole trip.
  final String summary;

  /// Courses this itinerary was drawn from.
  final List<TripSource> sources;

  /// The critic's blended score, 0..1 — feasibility plus requested-area
  /// coverage and foreigner-readiness. Null when the plan was never scored.
  final double? overallScore;

  /// The critic's feasibility term alone, 0..1: meal windows, travel time
  /// between stops and opening hours. The only score that speaks to whether
  /// the days can actually be completed.
  final double? feasibilityScore;

  /// The backend's itinerary payload, verbatim.
  ///
  /// Kept so an export carries the fields these typed models don't surface —
  /// critic_report, area_coverage, repair_log. Never read for display.
  final Map<String, dynamic> raw;

  int get stampedDays => days.where((d) => d.visitedCount > 0).length;

  /// Copies the itinerary with new [days], keeping the trip-level fields.
  ///
  /// Same reason as [TripDay.withActivities]: a check-in only changes which
  /// stops are visited, and hand-listing the fields around that change drops
  /// the summary, sources and critic scores every time a new one is added.
  Itinerary withDays(List<TripDay> days) => Itinerary(
        preferences: preferences,
        days: days,
        routeStops: routeStops,
        summary: summary,
        sources: sources,
        overallScore: overallScore,
        feasibilityScore: feasibilityScore,
        raw: raw,
      );
}
