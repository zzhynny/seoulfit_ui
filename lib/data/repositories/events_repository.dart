import '../../models/event.dart';

abstract class EventsRepository {
  /// Events for one of [kEventCategories], from 한국관광공사 TourAPI via the
  /// backend. The backend holds every Seoul event in one cached list and the
  /// chip filters it, so switching chips costs nothing upstream.
  Future<List<SeoulEvent>> fetchEvents(String category);
}
