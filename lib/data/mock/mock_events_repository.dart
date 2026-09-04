import 'package:flutter/material.dart';
import '../../models/event.dart';
import '../repositories/events_repository.dart';

class MockEventsRepository implements EventsRepository {
  @override
  Future<List<SeoulEvent>> fetchEvents() async {
    await Future.delayed(const Duration(milliseconds: 200));
    return const [
      SeoulEvent(
        title: 'Les Misérables',
        dateRange: 'Jun 5 – Aug 18',
        venue: 'Blue Square Shinhan Hall',
        category: 'Musical',
        posterColors: [Color(0xFF3A2E28), Color(0xFF8B2E22)],
        posterAsset: 'assets/images/event-les-miserables.png',
      ),
      SeoulEvent(
        title: 'Wicked',
        dateRange: 'Jun 10 – Aug 25',
        venue: 'Charlotte Theater',
        category: 'Musical',
        posterColors: [Color(0xFF0E1A12), Color(0xFF3FA34D)],
        posterAsset: 'assets/images/event-wicked.png',
      ),
      SeoulEvent(
        title: 'K-Pop World Tour',
        dateRange: 'Jul 1 – Jul 3',
        venue: 'KSPO Dome',
        category: 'Concert',
        posterColors: [Color(0xFF1B1032), Color(0xFFDA4CE0)],
        posterAsset: 'assets/images/event-kpop.png',
      ),
      SeoulEvent(
        title: 'Seoul Jazz Festival',
        dateRange: 'Jul 15 – Jul 17',
        venue: 'Olympic Park',
        category: 'Concert',
        posterColors: [Color(0xFFE08A3C), Color(0xFFF2C14E)],
        posterAsset: 'assets/images/event-jazz-festival.png',
      ),
    ];
  }
}
