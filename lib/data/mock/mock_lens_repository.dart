import '../../models/lens.dart';
import '../repositories/lens_repository.dart';

class MockLensRepository implements LensRepository {
  @override
  Future<LensPlaceResult> scanPlace() async {
    await Future.delayed(const Duration(milliseconds: 500));
    return const LensPlaceResult(
      name: 'N Seoul Tower',
      address: 'N Seoul Tower, Yongsan-gu',
      confidence: 99,
      hours:
          'Weekdays 10:00–22:30, Weekends 10:00–23:00 (Last entry 30 mins before closing)',
      openDays: 'Every day',
      closedNote: 'Open year-round',
      gettingThere:
          'Subway Line 3/4 Chungmuro Stn Exit 2 → Take Namsan Sunhwan Bus 01 → Walk 357m',
      hashtags: [
        '#SeoulDateSpot',
        '#NSeoulTower',
        '#NamsanTower',
        '#Myeongdong',
        '#NamsanPark',
        '#NightView',
      ],
      audioGuideCategory: 'AI Audio Guide · Tower',
      audioGuideTitle: 'Namsan sentinel of Seoul',
      audioGuideExcerpt:
          'As the city breathes beneath us, this tower, originally built to broadcast signals across Korea, has become a silent sentinel...',
    );
  }
}
