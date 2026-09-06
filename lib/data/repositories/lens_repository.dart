import '../../models/lens.dart';

abstract class LensRepository {
  /// Captures a photo from [source] and identifies it.
  ///
  /// Returns null when the user dismisses the camera or picker without
  /// choosing anything — a cancellation, not a failure, so callers should
  /// stay put rather than route on to a result screen.
  Future<LensPlaceResult?> scanPlace(LensPhotoSource source);
}
