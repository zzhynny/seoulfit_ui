import '../../models/profile.dart';

abstract class ProfileRepository {
  Future<UserProfile> fetchProfile();
  Future<List<RecapStampDay>> fetchStampDays();
  Future<List<RecapStop>> fetchRecapStops();

  /// Whether enough check-in data exists to render the full journey-map
  /// recap variant vs. the low-data variant.
  Future<bool> hasEnoughDataForFullRecap();
}
