import '../../models/lens.dart';

abstract class LensRepository {
  Future<LensPlaceResult> scanPlace();
}
