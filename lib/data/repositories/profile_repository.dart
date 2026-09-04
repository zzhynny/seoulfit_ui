import '../../models/profile.dart';

abstract class ProfileRepository {
  Future<UserProfile> fetchProfile();
}
