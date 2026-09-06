import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/trip_checkin.dart';
import 'api_service.dart';

/// Local-first store for trip check-ins, following the same
/// `shared_preferences` + JSON pattern as [TripStorageService].
///
/// The recap renders entirely from here; the backend copy written by
/// [ApiService.postCheckin] is best-effort and never read back.
class CheckinStore {
  static const _deviceKey = 'device_id';
  static const _tripPrefix = 'checkin_';
  static const _activeKey = 'active_trip_id';
  static const _alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';

  /// Stable per-install identifier, generated on first call. No account and no
  /// OAuth: this only needs to group one device's records, not authenticate a
  /// person. Mirrors `ApiService._newThreadId`'s alphabet so ids look alike in
  /// logs. Lost on reinstall — acceptable for a single trip's record.
  static Future<String> deviceId() async {
    final prefs = await SharedPreferences.getInstance();
    final existing = prefs.getString(_deviceKey);
    if (existing != null && existing.isNotEmpty) return existing;
    final rand = Random.secure();
    final id =
        'dev-${List.generate(16, (_) => _alphabet[rand.nextInt(36)]).join()}';
    await prefs.setString(_deviceKey, id);
    return id;
  }

  /// Writes locally, then mirrors to the backend. The local write is awaited;
  /// the upload is not — a slow or dead network must never make the check-in
  /// button feel broken.
  static Future<void> save(TripCheckin trip) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      '$_tripPrefix${trip.tripId}',
      jsonEncode(trip.toJson()),
    );
    // ApiService.threadId is generated fresh on every app launch and never
    // persisted, so remembering the most recently saved trip id here is what
    // lets a restarted app find yesterday's record again (see loadActive).
    await prefs.setString(_activeKey, trip.tripId);
    unawaited(_sync(trip));
  }

  static Future<void> _sync(TripCheckin trip) async {
    try {
      await ApiService().postCheckin(deviceId: await deviceId(), trip: trip);
    } catch (_) {
      // Best-effort: the local copy is the source of truth for the recap.
    }
  }

  static Future<TripCheckin?> load(String tripId) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('$_tripPrefix$tripId');
    if (raw == null) return null;
    return TripCheckin.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  /// The trip id most recently written by [save], or null if nothing has
  /// been saved yet on this device.
  static Future<String?> activeTripId() async {
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getString(_activeKey);
    return (id == null || id.isEmpty) ? null : id;
  }

  /// The record for [activeTripId], or null if there is none. Used to
  /// recover a check-in record after `ApiService.threadId` has changed out
  /// from under it, e.g. an app restart.
  static Future<TripCheckin?> loadActive() async {
    final id = await activeTripId();
    if (id == null) return null;
    return load(id);
  }
}
