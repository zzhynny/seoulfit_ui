/// Coerce `jsonDecode` output into `Map<String, dynamic>`. Nested maps from
/// `jsonDecode` are `Map<String, dynamic>` on the Dart VM but can come back as
/// `Map<dynamic, dynamic>` on web — going through `Map.from` works on both.
Map<String, dynamic>? _asJsonMap(Object? raw) {
  if (raw is Map) return Map<String, dynamic>.from(raw);
  return null;
}

List<Map<String, dynamic>> _asJsonList(Object? raw) {
  if (raw is! List) return const [];
  return [
    for (final item in raw)
      if (item is Map) Map<String, dynamic>.from(item),
  ];
}

/// Mirrors the StateResponse Pydantic model from the FastAPI backend.
class TravelState {
  final String? travelDates;
  final String? region;
  final String? restrictions;
  final String? category;
  final String? companion;
  final String? pace;
  final String currentStep;

  /// The slot the backend is waiting on right now ('travel_dates', 'category',
  /// …), or null outside the collecting step. Drives the per-question quick
  /// replies, the date picker and the progress line on the chat screen.
  final String? currentField;
  final bool confirmed;
  final String? reply;
  final Itinerary? itinerary;

  const TravelState({
    this.travelDates,
    this.region,
    this.restrictions,
    this.category,
    this.companion,
    this.pace,
    this.currentStep = 'start',
    this.currentField,
    this.confirmed = false,
    this.reply,
    this.itinerary,
  });

  factory TravelState.fromJson(Map<String, dynamic> json) {
    final itineraryJson = _asJsonMap(json['itinerary']);
    return TravelState(
      travelDates: json['travel_dates'] as String?,
      region: json['region'] as String?,
      restrictions: json['restrictions'] as String?,
      category: json['category'] as String?,
      companion: json['companion'] as String?,
      pace: json['pace'] as String?,
      currentStep: (json['current_step'] as String?) ?? 'start',
      currentField: json['current_field'] as String?,
      confirmed: (json['confirmed'] as bool?) ?? false,
      reply: json['reply'] as String?,
      itinerary:
          itineraryJson != null ? Itinerary.fromJson(itineraryJson) : null,
    );
  }

  /// Raw slot values keyed by backend field name.
  Map<String, String?> get slots => {
        'travel_dates': travelDates,
        'region': region,
        'restrictions': restrictions,
        'category': category,
        'companion': companion,
        'pace': pace,
      };
}

class Itinerary {
  final String summary;
  final List<ItineraryDay> days;
  final List<ItinerarySource> sources;

  /// The original JSON payload from the backend, kept verbatim so the export
  /// includes fields the typed model doesn't surface (critic_report, …).
  final Map<String, dynamic> raw;

  const Itinerary({
    required this.summary,
    required this.days,
    required this.sources,
    this.raw = const {},
  });

  factory Itinerary.fromJson(Map<String, dynamic> json) => Itinerary(
        summary: json['summary'] as String? ?? '',
        days: _asJsonList(json['days']).map(ItineraryDay.fromJson).toList(),
        sources: _asJsonList(json['sources'])
            .map(ItinerarySource.fromJson)
            .toList(),
        raw: json,
      );

  /// The deterministic feasibility term from the critic report — meal windows,
  /// travel time between stops, and opening hours. 0..1, or null if the plan
  /// was never scored.
  ///
  /// Deliberately not [overallScore]: that one blends in requested-area
  /// coverage and foreigner-readiness, neither of which says anything about
  /// whether a traveller can complete the plan.
  double? get feasibilityScore => _afterScore('feasibility_score');

  /// The blended critic score, 0..1.
  double? get overallScore {
    final direct = raw['overall_score'] ?? raw['score'];
    if (direct is num) return direct.toDouble();
    return _afterScore('overall_score');
  }

  /// `make_critic_repair_node` nests the scores under
  /// `critic_report.after`; the flat `critic_report[key]` lookup is kept only
  /// as a fallback for older payloads.
  double? _afterScore(String key) {
    final report = raw['critic_report'];
    if (report is! Map) return null;
    final after = report['after'];
    if (after is Map && after[key] is num) return (after[key] as num).toDouble();
    if (report[key] is num) return (report[key] as num).toDouble();
    return null;
  }
}

class ItineraryDay {
  final int day;
  final String theme;
  final List<Poi> pois;
  final String estimatedCost;
  final List<TransitLeg> transitLegs;

  const ItineraryDay({
    required this.day,
    required this.theme,
    required this.pois,
    required this.estimatedCost,
    this.transitLegs = const [],
  });

  factory ItineraryDay.fromJson(Map<String, dynamic> json) {
    final dayNum = (json['day'] as num?)?.toInt() ?? 0;
    return ItineraryDay(
      day: dayNum,
      theme: json['theme'] as String? ?? '',
      pois: _asJsonList(json['pois'])
          .map((p) => Poi.fromJson(p, day: dayNum))
          .toList(),
      estimatedCost: json['estimated_cost']?.toString() ?? '',
      transitLegs: _asJsonList(json['transit_legs'])
          .map(TransitLeg.fromJson)
          .toList(),
    );
  }
}

/// Distance + walk/car ETA + Kakao Map deep links between two consecutive
/// POIs in a single day.
class TransitLeg {
  final double? distanceKm;
  final int? walkMinutes;
  final int? carMinutes;
  final String? kakaoWalkUrl;
  final String? kakaoCarUrl;
  final List<TransitOption> transitOptions;

  const TransitLeg({
    this.distanceKm,
    this.walkMinutes,
    this.carMinutes,
    this.kakaoWalkUrl,
    this.kakaoCarUrl,
    this.transitOptions = const [],
  });

  factory TransitLeg.fromJson(Map<String, dynamic> json) => TransitLeg(
        distanceKm: (json['distance_km'] as num?)?.toDouble(),
        walkMinutes: (json['walk_minutes'] as num?)?.toInt(),
        carMinutes: (json['car_minutes'] as num?)?.toInt(),
        kakaoWalkUrl: json['kakao_walk_url'] as String?,
        kakaoCarUrl: json['kakao_car_url'] as String?,
        transitOptions: _asJsonList(json['transit_options'])
            .map(TransitOption.fromJson)
            .toList(),
      );

  bool get hasAnyData =>
      distanceKm != null || walkMinutes != null || carMinutes != null;
}

/// One leg's transit option (subway / bus / transfer). Extracted from ODsay.
class TransitOption {
  final int? type; // 1=subway, 2=bus, 3=transfer
  final String typeLabel;
  final int? totalMinutes;
  final int? fareWon;
  final int? walkMeters;
  final int? subwayRides;
  final int? busRides;
  final int? transfers;
  final List<String> segments;

  const TransitOption({
    this.type,
    required this.typeLabel,
    this.totalMinutes,
    this.fareWon,
    this.walkMeters,
    this.subwayRides,
    this.busRides,
    this.transfers,
    this.segments = const [],
  });

  factory TransitOption.fromJson(Map<String, dynamic> json) {
    final rawSegs = json['segments'];
    final segs = rawSegs is List
        ? [for (final s in rawSegs) s.toString()]
        : const <String>[];
    return TransitOption(
      type: (json['type'] as num?)?.toInt(),
      typeLabel: json['type_label']?.toString() ?? '',
      totalMinutes: (json['total_minutes'] as num?)?.toInt(),
      fareWon: (json['fare_won'] as num?)?.toInt(),
      walkMeters: (json['walk_meters'] as num?)?.toInt(),
      subwayRides: (json['subway_rides'] as num?)?.toInt(),
      busRides: (json['bus_rides'] as num?)?.toInt(),
      transfers: (json['transfers'] as num?)?.toInt(),
      segments: segs,
    );
  }
}

class Poi {
  final String name;
  final String type;
  final String address;
  final double? lat;
  final double? lng;
  final int stayMinutes;
  final String notes;

  /// Neighborhood key (e.g. "jongno", "hongdae") — critic_repair.as_output_poi
  /// already sends this, it just wasn't read here before. Needed as the
  /// `day_area` param for POST /swap-candidates.
  final String? area;

  /// Itinerary day this POI belongs to (1-based), injected from the parent
  /// [ItineraryDay] so the day grouping survives even when POIs are flattened
  /// into a single list (selection screen, route summary). 0 if unknown.
  final int day;

  const Poi({
    required this.name,
    required this.type,
    required this.address,
    this.lat,
    this.lng,
    required this.stayMinutes,
    required this.notes,
    this.area,
    this.day = 0,
  });

  factory Poi.fromJson(Map<String, dynamic> json, {int day = 0}) => Poi(
        name: json['name'] as String? ?? '',
        type: json['type'] as String? ?? '',
        address: json['address'] as String? ?? '',
        lat: (json['lat'] as num?)?.toDouble(),
        lng: (json['lng'] as num?)?.toDouble(),
        stayMinutes: (json['stay_minutes'] as num?)?.toInt() ?? 0,
        notes: json['notes'] as String? ?? '',
        area: json['area'] as String?,
        day: day,
      );
}

class ItinerarySource {
  final String courseId;
  final String courseTitle;
  final String source;
  final String sourceUrl;

  const ItinerarySource({
    required this.courseId,
    required this.courseTitle,
    required this.source,
    required this.sourceUrl,
  });

  factory ItinerarySource.fromJson(Map<String, dynamic> json) =>
      ItinerarySource(
        courseId: json['course_id']?.toString() ?? '',
        courseTitle: json['course_title'] as String? ?? '',
        source: json['source'] as String? ?? '',
        sourceUrl: json['source_url'] as String? ?? '',
      );
}
