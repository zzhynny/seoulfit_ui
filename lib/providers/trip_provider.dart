import 'dart:async';

import 'package:flutter/foundation.dart';
import '../data/repositories/trip_repository.dart';
import '../models/plan_check.dart';
import '../models/trip_checkin.dart';
import '../services/checkin_store.dart';
import '../models/trip.dart';

class TripProvider extends ChangeNotifier {
  TripProvider(this._repository);

  final TripRepository _repository;

  Itinerary? _itinerary;
  Itinerary? get itinerary => _itinerary;
  bool get hasItinerary => _itinerary != null;

  int _selectedDay = 1;
  int get selectedDay => _selectedDay;

  bool _stampCollectionEnabled = false;
  bool get stampCollectionEnabled => _stampCollectionEnabled;

  /// Whether the user has already answered the 13_Stamp-Book-OptIn prompt
  /// this trip. Once true, the "Check in for today's places" button on
  /// Final Route skips straight to Day Check-in instead of re-asking.
  bool _hasRespondedToStampOptIn = false;
  bool get hasRespondedToStampOptIn => _hasRespondedToStampOptIn;

  /// True once the user has gone through 16_Trip-Finish-Confirm and chosen
  /// to see their recap — takes priority over the stamp opt-in check on
  /// Final Route's "Check in for today's places" button, since there's
  /// nothing left to check in once the trip is wrapped up.
  bool _tripCompleted = false;
  bool get isTripCompleted => _tripCompleted;

  void markTripCompleted() {
    _tripCompleted = true;
    notifyListeners();
  }

  final Map<String, MissedReason> _missedReasons = {};

  bool _loading = false;
  bool get loading => _loading;

  /// Loads the plan the Trip tab shows, once.
  ///
  /// Returns early when one is already in memory. The server's copy carries
  /// no check-ins, so refetching on every remount of the Trip tab silently
  /// erased every stamp the traveller had just collected.
  ///
  /// The fetch is guarded because /state throws on a timeout or any non-200:
  /// the uncaught throw left [_loading] true forever, so the Trip tab stayed
  /// a spinner — no Final Route, and no "Check in for today's places" button,
  /// which is the only way into the stamp / check-in / recap flow.
  Future<void> loadCurrentTrip() async {
    if (_itinerary != null) return;
    _loading = true;
    notifyListeners();
    try {
      _itinerary = await _repository.fetchCurrentItinerary();
    } catch (e) {
      // Landing on Trip_Empty-State at least offers a way to start planning.
      debugPrint('[trip] loadCurrentTrip failed, showing empty state: $e');
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> generateItinerary() async {
    final prefs = await _repository.fetchDefaultPreferences();
    _itinerary = await _repository.generateItinerary(prefs);
    _selectedDay = 1;
    notifyListeners();
  }

  /// Stops the user chose to replace, as `current name -> replacement name`.
  /// Applied on the next [reoptimize] and cleared once the backend has
  /// persisted them, so a later edit doesn't re-apply a swap already baked
  /// into the plan.
  final Map<String, String> _pendingSwaps = {};
  Map<String, String> get pendingSwaps => Map.unmodifiable(_pendingSwaps);

  void swapActivity(String activityId, String replacementName) {
    _pendingSwaps[activityId] = replacementName;
    notifyListeners();
  }

  String? pendingSwapFor(String activityId) => _pendingSwaps[activityId];

  /// The critic's before/after verdict from the last [reoptimize]. Null until
  /// the user has optimized at least once.
  ReoptimizeResult? _lastPlanCheck;
  ReoptimizeResult? get lastPlanCheck => _lastPlanCheck;

  /// Takes the pending verdict and clears it, so landing on Final Route shows
  /// the sheet exactly once per optimize rather than on every tab switch.
  ReoptimizeResult? consumePlanCheck() {
    final result = _lastPlanCheck;
    _lastPlanCheck = null;
    return result;
  }

  Future<void> reoptimize() async {
    if (_itinerary == null) return;
    final (itinerary, result) = await _repository.reoptimizeItinerary(
      _itinerary!,
      swappedSlots: Map.of(_pendingSwaps),
    );
    _itinerary = itinerary;
    _lastPlanCheck = result;
    _pendingSwaps.clear();
    notifyListeners();
  }

  void selectDay(int dayNumber) {
    _selectedDay = dayNumber;
    notifyListeners();
  }

  TripDay? get currentDay {
    final itinerary = _itinerary;
    if (itinerary == null) return null;
    return itinerary.days.firstWhere(
      (d) => d.dayNumber == _selectedDay,
      orElse: () => itinerary.days.first,
    );
  }

  void toggleActivityIncluded(String activityId, bool included) {
    _mutateActivity(activityId, (a) => a.copyWith(included: included));
  }

  void checkIn(String activityId) => setVisited(activityId, true);

  /// Marks a stop visited, or un-marks it.
  ///
  /// Reversible on purpose: this is the only control on the check-in screen,
  /// so a mis-tap with no way back would strand a wrong stamp in the record.
  void setVisited(String activityId, bool visited) {
    _mutateActivity(activityId, (a) => a.copyWith(visited: visited));
    unawaited(_persistCheckins());
  }

  void markMissed(String activityId, MissedReason reason) {
    _missedReasons[activityId] = reason;
    notifyListeners();
    unawaited(_persistCheckins());
  }

  /// Writes the trip's check-in record to local storage (and, best-effort,
  /// to the backend's research table).
  ///
  /// Without this the record only ever existed in memory: Profile's stamp
  /// and spot counts read [CheckinStore] and were therefore always zero, the
  /// recap had nothing to survive a restart with, and nothing ever reached
  /// POST /trip/checkin.
  ///
  /// Fire-and-forget by design — a slow write must never make the check-in
  /// button feel stuck, and the in-memory itinerary is what the screen is
  /// already rendering.
  Future<void> _persistCheckins() async {
    final itinerary = _itinerary;
    if (itinerary == null) return;

    final tripId = _tripId ??= 'trip-${DateTime.now().millisecondsSinceEpoch}';
    final planned = <int, List<String>>{};
    final coords = <String, List<double>>{};
    final checkins = <int, DayCheckin>{};

    for (final day in itinerary.days) {
      planned[day.dayNumber] = [for (final a in day.activities) a.id];

      final visited = <String>{};
      final misses = <String, MissReason>{};
      for (final activity in day.activities) {
        final lat = activity.lat;
        final lng = activity.lng;
        if (lat != null && lng != null) coords[activity.id] = [lat, lng];
        if (activity.visited) visited.add(activity.id);
        final reason = _missedReasons[activity.id];
        if (reason != null) misses[activity.id] = _missReasonOf(reason);
      }
      // A day nobody has touched stays unrecorded, which every aggregate
      // excludes — recording it empty would read as "visited nothing".
      if (visited.isNotEmpty || misses.isNotEmpty) {
        checkins[day.dayNumber] = DayCheckin(visited: visited, misses: misses);
      }
    }

    await CheckinStore.save(TripCheckin(
      tripId: tripId,
      planned: planned,
      checkins: checkins,
      coords: coords,
    ));
  }

  /// The id this trip's record is stored under. Generated on first check-in
  /// rather than taken from ApiService.threadId, which is regenerated every
  /// launch and would orphan yesterday's stamps.
  String? _tripId;
  String? get tripId => _tripId;

  static MissReason _missReasonOf(MissedReason reason) {
    switch (reason) {
      case MissedReason.notEnoughTime:
        return MissReason.time;
      case MissedReason.tooTired:
        return MissReason.stamina;
      case MissedReason.didntFeelLikeIt:
        return MissReason.notInterested;
      case MissedReason.other:
        return MissReason.other;
    }
  }

  MissedReason? reasonFor(String activityId) => _missedReasons[activityId];

  /// Records the user's answer to the 13_Stamp-Book-OptIn prompt.
  void respondToStampOptIn(bool enabled) {
    _stampCollectionEnabled = enabled;
    _hasRespondedToStampOptIn = true;
    notifyListeners();
  }

  void resetItinerary() {
    _itinerary = null;
    _selectedDay = 1;
    _missedReasons.clear();
    _stampCollectionEnabled = false;
    _hasRespondedToStampOptIn = false;
    _tripCompleted = false;
    _pendingSwaps.clear();
    _lastPlanCheck = null;
    notifyListeners();
  }

  void _mutateActivity(String activityId, TripActivity Function(TripActivity) update) {
    final itinerary = _itinerary;
    if (itinerary == null) return;
    final newDays = itinerary.days.map((day) {
      final newActivities = day.activities.map((a) {
        return a.id == activityId ? update(a) : a;
      }).toList();
      return day.withActivities(newActivities);
    }).toList();
    _itinerary = itinerary.withDays(newDays);
    notifyListeners();
  }
}
