import '../../models/event.dart';

abstract class EventsRepository {
  /// Events for one of [kEventCategories]. The backend scrapes a single
  /// genre page per call, so switching chips is a refetch, not a filter.
  Future<List<SeoulEvent>> fetchEvents(String category);
}
