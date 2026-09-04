import 'package:flutter/foundation.dart';
import '../data/repositories/trip_repository.dart';
import '../models/trip.dart';

class TripProvider extends ChangeNotifier {
  TripProvider(this._repository);

  final TripRepository _repository;

  Itinerary? _itinerary;
  Itinerary? get itinerary => _itinerary;
  bool get hasItinerary => _itinerary != null;

  int _selectedDay = 1;
  int get selectedDay => _selectedDay;

  bool _stampCollectionEnabled = true;
  bool get stampCollectionEnabled => _stampCollectionEnabled;

  final Map<String, MissedReason> _missedReasons = {};

  bool _loading = false;
  bool get loading => _loading;

  Future<void> loadCurrentTrip() async {
    _loading = true;
    notifyListeners();
    _itinerary = await _repository.fetchCurrentItinerary();
    _loading = false;
    notifyListeners();
  }

  Future<void> generateItinerary() async {
    final prefs = await _repository.fetchDefaultPreferences();
    _itinerary = await _repository.generateItinerary(prefs);
    _selectedDay = 1;
    notifyListeners();
  }

  Future<void> reoptimize() async {
    if (_itinerary == null) return;
    _itinerary = await _repository.reoptimizeItinerary(_itinerary!);
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

  void checkIn(String activityId) {
    _mutateActivity(activityId, (a) => a.copyWith(visited: true));
  }

  void markMissed(String activityId, MissedReason reason) {
    _missedReasons[activityId] = reason;
    notifyListeners();
  }

  MissedReason? reasonFor(String activityId) => _missedReasons[activityId];

  void setStampCollectionEnabled(bool value) {
    _stampCollectionEnabled = value;
    notifyListeners();
  }

  void resetItinerary() {
    _itinerary = null;
    _selectedDay = 1;
    _missedReasons.clear();
    notifyListeners();
  }

  void _mutateActivity(String activityId, TripActivity Function(TripActivity) update) {
    final itinerary = _itinerary;
    if (itinerary == null) return;
    final newDays = itinerary.days.map((day) {
      final newActivities = day.activities.map((a) {
        return a.id == activityId ? update(a) : a;
      }).toList();
      return TripDay(
        dayNumber: day.dayNumber,
        date: day.date,
        areaName: day.areaName,
        activities: newActivities,
      );
    }).toList();
    _itinerary = Itinerary(
      preferences: itinerary.preferences,
      days: newDays,
      routeStops: itinerary.routeStops,
    );
    notifyListeners();
  }
}
