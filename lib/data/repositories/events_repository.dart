import '../../models/event.dart';

abstract class EventsRepository {
  Future<List<SeoulEvent>> fetchEvents();
}
