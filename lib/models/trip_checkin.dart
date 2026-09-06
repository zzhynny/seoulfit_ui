import 'travel_state.dart';

/// Why a planned stop went unvisited. Stored per POI and deliberately kept out
/// of the completion rate: the feasibility score measures whether a plan is
/// physically doable, not whether the traveller felt like going.
enum MissReason { time, stamina, notInterested, other }

MissReason _reasonFromJson(String s) => MissReason.values.firstWhere(
      (r) => r.name == s,
      orElse: () => MissReason.other,
    );

/// Stamp shown for one day. Presentation only — the exact visited/planned
/// counts are always persisted alongside it.
enum StampTier { full, faded, none }

/// What the traveller reported for one day. A day with no [DayCheckin] at all
/// is "unrecorded" and is excluded from every aggregate.
class DayCheckin {
  final Set<String> visited;
  final Map<String, MissReason> misses;

  const DayCheckin({this.visited = const {}, this.misses = const {}});

  Map<String, dynamic> toJson() => {
        'visited': visited.toList(),
        'misses': misses.map((k, v) => MapEntry(k, v.name)),
      };

  factory DayCheckin.fromJson(Map<String, dynamic> json) => DayCheckin(
        visited: ((json['visited'] as List?) ?? const []).cast<String>().toSet(),
        misses: ((json['misses'] as Map?) ?? const {}).map(
          (k, v) => MapEntry(k as String, _reasonFromJson(v as String)),
        ),
      );
}

/// One visited stop with a place on the map, in plan order.
class VisitedPoint {
  final String name;
  final double lat;
  final double lng;

  const VisitedPoint(this.name, this.lat, this.lng);

  @override
  bool operator ==(Object other) =>
      other is VisitedPoint &&
      other.name == name &&
      other.lat == lat &&
      other.lng == lng;

  @override
  int get hashCode => Object.hash(name, lat, lng);

  @override
  String toString() => 'VisitedPoint($name, $lat, $lng)';
}

/// One trip's check-in record. [planned] is snapshotted from the confirmed
/// selection at creation time — `TravelProvider.selectedStops` lives in memory
/// only and would be gone by the second evening.
class TripCheckin {
  final String tripId;

  /// Day number → planned POI names, in visit order.
  final Map<int, List<String>> planned;

  /// Day number → what the traveller reported. A missing key means unrecorded.
  final Map<int, DayCheckin> checkins;

  /// `critic_report.after.feasibility_score` at confirmation time, 0..1.
  final double? feasibilityScore;

  /// POI name → `[lat, lng]`, snapshotted alongside [planned].
  ///
  /// Kept separate from [planned] on purpose: the completion-rate,
  /// stamp and data-sufficiency logic all read [planned] and must not have to
  /// care whether a stop happens to have coordinates. Stops the backend sent
  /// without a location are simply absent here.
  final Map<String, List<double>> coords;

  /// Districts ("종로구", "성북구") seen across the snapshotted stops. Used to
  /// title the recap; empty when no address carried one.
  final Set<String> areas;

  const TripCheckin({
    required this.tripId,
    required this.planned,
    this.checkins = const {},
    this.feasibilityScore,
    this.coords = const {},
    this.areas = const {},
  });

  /// Snapshot the confirmed selection. Day 0 normalises to 1, matching the
  /// route screen's grouping.
  factory TripCheckin.fromStops(
    String tripId,
    List<Poi> stops,
    double? feasibilityScore,
  ) {
    final planned = <int, List<String>>{};
    final coords = <String, List<double>>{};
    final areas = <String>{};
    for (final s in stops) {
      (planned[s.day == 0 ? 1 : s.day] ??= <String>[]).add(s.name);
      final lat = s.lat;
      final lng = s.lng;
      if (lat != null && lng != null) coords[s.name] = [lat, lng];
      final area = _districtOf(s.address);
      if (area != null) areas.add(area);
    }
    return TripCheckin(
      tripId: tripId,
      planned: planned,
      feasibilityScore: feasibilityScore,
      coords: coords,
      areas: areas,
    );
  }

  /// First whitespace-delimited token ending in 구, e.g. "종로구" out of
  /// "서울특별시 종로구 사직로 161". Null when the address carries none — a
  /// missing district only costs the recap its title.
  static String? _districtOf(String address) {
    for (final token in address.split(RegExp(r'\s+'))) {
      if (token.length >= 2 && token.endsWith('구')) return token;
    }
    return null;
  }

  List<int> get plannedDays => planned.keys.toList()..sort();
  List<int> get checkedDays => checkins.keys.toList()..sort();

  /// Visited / planned for one day, or null if that day was never checked in.
  double? dayRate(int day) {
    final entry = checkins[day];
    final stops = planned[day];
    if (entry == null || stops == null || stops.isEmpty) return null;
    return entry.visited.where(stops.contains).length / stops.length;
  }

  StampTier stampFor(int day) {
    final rate = dayRate(day);
    if (rate == null) return StampTier.none;
    if (rate >= 0.80) return StampTier.full;
    if (rate >= 0.50) return StampTier.faded;
    return StampTier.none;
  }

  /// Completion over checked-in days only — unrecorded days leave both sides
  /// of the fraction untouched, so a forgotten evening never reads as failure.
  /// Null when nothing has been checked in yet.
  double? get completionRate {
    var visited = 0;
    var total = 0;
    for (final day in checkedDays) {
      final stops = planned[day];
      if (stops == null || stops.isEmpty) continue;
      visited += checkins[day]!.visited.where(stops.contains).length;
      total += stops.length;
    }
    return total == 0 ? null : visited / total;
  }

  /// Guards any comparison against the feasibility score: one checked day out
  /// of five says nothing about the trip.
  bool get hasEnoughData =>
      planned.isNotEmpty && checkedDays.length / planned.length >= 0.5;

  /// The stops actually visited on [day] that have a location, in plan order.
  ///
  /// Plan order, not the order [DayCheckin.visited] happens to iterate: the map
  /// draws these as a path, so the sequence is the whole point. Empty for an
  /// unrecorded day, and for records written before coordinates were stored.
  List<VisitedPoint> visitedPointsFor(int day) {
    final entry = checkins[day];
    final stops = planned[day];
    if (entry == null || stops == null) return const [];
    final points = <VisitedPoint>[];
    for (final name in stops) {
      if (!entry.visited.contains(name)) continue;
      final c = coords[name];
      if (c == null || c.length < 2) continue;
      points.add(VisitedPoint(name, c[0], c[1]));
    }
    return points;
  }

  TripCheckin withDay(int day, DayCheckin entry) => TripCheckin(
        tripId: tripId,
        planned: planned,
        checkins: {...checkins, day: entry},
        feasibilityScore: feasibilityScore,
        coords: coords,
        areas: areas,
      );

  Map<String, dynamic> toJson() => {
        'trip_id': tripId,
        'planned': planned.map((k, v) => MapEntry(k.toString(), v)),
        'checkins': checkins.map((k, v) => MapEntry(k.toString(), v.toJson())),
        'feasibility_score': feasibilityScore,
        'coords': coords,
        'areas': areas.toList(),
      };

  factory TripCheckin.fromJson(Map<String, dynamic> json) => TripCheckin(
        tripId: json['trip_id'] as String? ?? '',
        planned: ((json['planned'] as Map?) ?? const {}).map(
          (k, v) => MapEntry(
            int.parse(k as String),
            (v as List).cast<String>(),
          ),
        ),
        checkins: ((json['checkins'] as Map?) ?? const {}).map(
          (k, v) => MapEntry(
            int.parse(k as String),
            DayCheckin.fromJson(Map<String, dynamic>.from(v as Map)),
          ),
        ),
        feasibilityScore: (json['feasibility_score'] as num?)?.toDouble(),
        // Absent in records written before the recap grew a map.
        coords: ((json['coords'] as Map?) ?? const {}).map(
          (k, v) => MapEntry(
            k as String,
            (v as List).map((n) => (n as num).toDouble()).toList(),
          ),
        ),
        areas: ((json['areas'] as List?) ?? const []).cast<String>().toSet(),
      );
}
