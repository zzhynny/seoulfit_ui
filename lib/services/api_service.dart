import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

import '../config/api_base.dart';
import '../models/travel_state.dart';
import '../models/trip_checkin.dart';

class ApiService {
  static final Map<String, String> _poiCache = {};

  static String get _base => apiBase;

  /// Per-instance thread id. With auth=none we don't want every visitor
  /// landing on the same shared LangGraph thread, so each ApiService instance
  /// gets a fresh random id. Override via `ApiService(threadId: '...')` to
  /// resume a specific conversation.
  final String threadId;

  ApiService({String? threadId}) : threadId = threadId ?? _newThreadId();

  static String _newThreadId() {
    final ts = DateTime.now().millisecondsSinceEpoch.toRadixString(36);
    final rand = Random.secure();
    final tail = List.generate(
      8,
      (_) => 'abcdefghijklmnopqrstuvwxyz0123456789'[rand.nextInt(36)],
    ).join();
    return 'trip-$ts-$tail';
  }

  /// Conversational turns: collect_node plus one Gemini call, measured at
  /// 3-7s. 30s is generous headroom without leaving a dead network hanging.
  static const chatTimeout = Duration(seconds: 30);

  /// The 'confirm' turn instead runs RAG retrieval, the planner and
  /// critic-repair end to end — measured at 71s against a warm local backend,
  /// so it needs its own budget. Anything at or below the conversational
  /// timeout silently fails itinerary generation and the app reports
  /// "Need a bit more info".
  static const generationTimeout = Duration(seconds: 180);

  /// Sends a user message (or null for the initial greeting) and returns
  /// the updated [TravelState] including the latest AI reply.
  ///
  /// [timeout] defaults to [chatTimeout]; pass [generationTimeout] for the
  /// turn that builds the itinerary.
  Future<TravelState> chat(String? message, {Duration? timeout}) async {
    final body = jsonEncode({
      'thread_id': threadId,
      'message': message,
    });

    // Some timeout is needed: without one this hangs forever against a host
    // that drops packets instead of refusing them — a sleeping Render
    // instance, a firewall DROP, a wrong LAN IP — and TravelProvider keeps
    // `loading` true for the whole wait.
    final response = await http
        .post(
          Uri.parse('$_base/chat'),
          headers: {'Content-Type': 'application/json'},
          body: body,
        )
        .timeout(timeout ?? chatTimeout);

    if (response.statusCode == 200) {
      final json =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      return TravelState.fromJson(json);
    } else {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }
  }

  /// Resets the conversation on the backend.
  Future<void> reset() async {
    await http
        .post(Uri.parse('$_base/reset?thread_id=$threadId'))
        .timeout(const Duration(seconds: 8));
  }

  /// POSTs `{name, type}` to a `/poi-*` endpoint and returns `json[field]`,
  /// caching by endpoint+name. Empty string on any non-200. Shared by the four
  /// single-field POI lookups below.
  Future<String> _fetchPoiField(
      String endpoint, String field, String name, String type) async {
    final cacheKey = '$endpoint|$name';
    final cached = _poiCache[cacheKey];
    if (cached != null) return cached;
    final response = await http.post(
      Uri.parse('$_base/$endpoint'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'name': name, 'type': type}),
    );
    if (response.statusCode != 200) return '';
    final json =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    final result = (json[field] as String?) ?? '';
    _poiCache[cacheKey] = result;
    return result;
  }

  /// 1–2 sentence Gemini summary for a Seoul POI.
  Future<String> fetchPoiSummary(String name, {String type = ''}) =>
      _fetchPoiField('poi-summary', 'summary', name, type);

  /// Best-matching thumbnail for a Seoul POI via SerpApi + Gemini.
  Future<String> fetchPoiImage(String name, {String type = ''}) =>
      _fetchPoiField('poi-image', 'image_url', name, type);

  /// Structured Tavily visitor info for a Seoul POI (stop selection screen).
  Future<String> fetchPoiDetail(String name, {String type = ''}) =>
      _fetchPoiField('poi-detail', 'detail', name, type);

  /// Short "you've arrived" confirmation tip — a visible landmark to recognise
  /// plus what's at the entrance.
  Future<String> fetchPoiArrivalTip(String name, {String type = ''}) =>
      _fetchPoiField('poi-arrival-tip', 'arrival_tip', name, type);

  /// Recomputes transit (distance / walk / car / Kakao / ODsay) for an
  /// arbitrary ordered list of [stops]. Returns one leg per consecutive pair.
  Future<List<TransitLeg>> fetchTransitLegs(List<Poi> stops) async {
    final body = jsonEncode({
      'stops': [
        for (final s in stops) {'name': s.name, 'lat': s.lat, 'lng': s.lng},
      ],
    });

    final response = await http.post(
      Uri.parse('$_base/transit-legs'),
      headers: {'Content-Type': 'application/json'},
      body: body,
    );

    if (response.statusCode == 200) {
      final json =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final list = json['transit_legs'] as List? ?? const [];
      return [
        for (final l in list)
          if (l is Map) TransitLeg.fromJson(Map<String, dynamic>.from(l)),
      ];
    } else {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }
  }

  /// Ranks up to 3 replacement candidates for [currentPoi] in [dayArea],
  /// each with pre-computed warnings (e.g. closed on the day's weekday).
  /// Returns the raw `candidates` list as-is — the selection screen reads it
  /// directly since it's already shaped for display, not worth a typed model.
  Future<List<Map<String, dynamic>>> fetchSwapCandidates({
    required int day,
    required int slotIndex,
    required String currentPoi,
    required String dayArea,
    String? currentPoiType,
    List<String> excludedIds = const [],
  }) async {
    final response = await http
        .post(
          Uri.parse('$_base/swap-candidates'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'thread_id': threadId,
            'day': day,
            'slot_index': slotIndex,
            'current_poi': currentPoi,
            'day_area': dayArea,
            'current_poi_type': currentPoiType,
            'excluded_ids': excludedIds,
          }),
        )
        .timeout(const Duration(seconds: 20));

    if (response.statusCode != 200) {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }
    final json =
        jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    final list = json['candidates'] as List? ?? const [];
    return [
      for (final c in list)
        if (c is Map) Map<String, dynamic>.from(c),
    ];
  }

  /// Re-runs Critic -> Repair -> Critic on the persisted itinerary with the
  /// given slot edits applied, and persists the repaired result so the next
  /// call (another swap, another revalidate) builds on top of it. Returns the
  /// raw response — `before`/`after` critic reports plus `repaired_itinerary`.
  Future<Map<String, dynamic>> revalidate({
    List<String> excludedIds = const [],
    Map<String, String> swappedSlots = const {},
    Map<String, List<String>> dayOrder = const {},
    Map<String, int> dayStartShift = const {},
  }) async {
    final response = await http
        .post(
          Uri.parse('$_base/revalidate'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'thread_id': threadId,
            'edits': {
              'excluded_ids': excludedIds,
              'swapped_slots': swappedSlots,
              'day_order': dayOrder,
              'day_start_shift': dayStartShift,
            },
          }),
        )
        .timeout(const Duration(seconds: 30));

    if (response.statusCode != 200) {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  /// Sends one trip's check-in snapshot to the backend. Write-only and
  /// best-effort: the client renders its recap from local storage, so a false
  /// here costs nothing but a missing row in the research table.
  Future<bool> postCheckin({
    required String deviceId,
    required TripCheckin trip,
  }) async {
    try {
      final response = await http
          .post(
            Uri.parse('$_base/trip/checkin'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'trip_id': trip.tripId,
              'device_id': deviceId,
              'itinerary': {
                'planned': trip.planned.map((k, v) => MapEntry(k.toString(), v)),
                'feasibility_score': trip.feasibilityScore,
                // Carried so offline analysis can place a trip on a map
                // without re-resolving POI names to coordinates.
                'coords': trip.coords,
                'areas': trip.areas.toList(),
              },
              'days': trip.checkins
                  .map((k, v) => MapEntry(k.toString(), v.toJson())),
            }),
          )
          .timeout(const Duration(seconds: 8));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}
