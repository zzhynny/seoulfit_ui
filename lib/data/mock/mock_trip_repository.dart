import '../../models/trip.dart';
import '../repositories/trip_repository.dart';

class MockTripRepository implements TripRepository {
  /// Set to a built itinerary to simulate a returning user with a plan
  /// already in progress; leave null to land on Trip_Empty-State.
  Itinerary? seedItinerary;

  @override
  Future<Itinerary?> fetchCurrentItinerary() async {
    await Future.delayed(const Duration(milliseconds: 200));
    return seedItinerary;
  }

  @override
  Future<TripPreferences> fetchDefaultPreferences() async {
    return const TripPreferences(
      dateRange: 'Oct 12 – Oct 16',
      duration: '5 Days (Autumn)',
      travelStyle: 'Culture, K-Pop',
      groupSize: '2 Adults',
      dietaryNotes: 'Vegan Options',
    );
  }

  @override
  Future<Itinerary> generateItinerary(TripPreferences preferences) async {
    await Future.delayed(const Duration(milliseconds: 300));
    final itinerary = Itinerary(
      preferences: preferences,
      days: _buildDays(),
      routeStops: _buildRouteStops(),
    );
    seedItinerary = itinerary;
    return itinerary;
  }

  @override
  Future<Itinerary> reoptimizeItinerary(Itinerary itinerary) async {
    await Future.delayed(const Duration(milliseconds: 300));
    seedItinerary = itinerary;
    return itinerary;
  }

  List<TripDay> _buildDays() {
    return [
      TripDay(
        dayNumber: 1,
        date: 'Oct 12',
        areaName: 'Jongno Area',
        activities: [
          const TripActivity(
            id: 'd1-1',
            time: '09:30 AM',
            category: ActivityCategory.culture,
            title: 'Gyeongbokgung Palace',
            description:
                'Experience the grand royal guard changing ceremony. Beautiful autumn ginkgo tree avenues.',
            imageAsset: 'assets/images/thumb-palace.png',
            visited: true,
          ),
          const TripActivity(
            id: 'd1-2',
            time: '12:30 PM',
            category: ActivityCategory.food,
            title: 'Osegye Hyang Vegan',
            description:
                'Cozy Hanok eatery in Insadong neighborhood serving incredible traditional Korean vegan temple cuisine.',
            imageAsset: 'assets/images/thumb-food-vegan.png',
            visited: true,
            aiInsight:
                'Opening Hours: 11:30 AM – 9:00 PM\nWhy we picked this: Perfect temple cuisine matching your Vegan preferences, located in a quiet, cozy Hanok courtyard.',
          ),
          const TripActivity(
            id: 'd1-3',
            time: '02:30 PM',
            category: ActivityCategory.teaHouse,
            title: 'Cha-Teul Traditional Tea',
            description: 'Traditional Korean tea house in a quiet courtyard.',
            imageAsset: 'assets/images/thumb-teahouse.png',
          ),
          const TripActivity(
            id: 'd1-4',
            time: '03:00 PM',
            category: ActivityCategory.crafts,
            title: 'Artisan Stamp Shop',
            description:
                'Browse locally crafted paper goods, handmade Korean stamps, and contemporary design artifacts.',
            imageAsset: 'assets/images/thumb-craft-stamp.png',
            included: false,
          ),
        ],
      ),
      TripDay(
        dayNumber: 2,
        date: 'Oct 13',
        areaName: 'Bukchon Area',
        activities: [
          const TripActivity(
            id: 'd2-1',
            time: '10:00 AM',
            category: ActivityCategory.culture,
            title: 'Bukchon Hanok Village',
            description: 'Wander traditional hanok alleyways with skyline views.',
            imageAsset: 'assets/images/thumb-palace.png',
            visited: true,
          ),
          const TripActivity(
            id: 'd2-2',
            time: '01:00 PM',
            category: ActivityCategory.food,
            title: 'Samcheong-dong Café Street',
            description: 'Cafes and dessert spots along a quiet, leafy street.',
            imageAsset: 'assets/images/thumb-teahouse.png',
            visited: true,
          ),
        ],
      ),
      TripDay(
        dayNumber: 3,
        date: 'Oct 14',
        areaName: 'Namsan Area',
        activities: [
          const TripActivity(
            id: 'd3-1',
            time: '11:00 AM',
            category: ActivityCategory.nature,
            title: 'Namsan Park Trail',
            description: 'Hike up through autumn foliage to N Seoul Tower.',
            imageAsset: 'assets/images/lens-result-hero.png',
            visited: true,
          ),
          const TripActivity(
            id: 'd3-2',
            time: '02:00 PM',
            category: ActivityCategory.culture,
            title: 'N Seoul Tower',
            description: "Seoul's iconic observation tower and locks fence.",
            imageAsset: 'assets/images/lens-scan-bg.png',
          ),
          const TripActivity(
            id: 'd3-3',
            time: '05:00 PM',
            category: ActivityCategory.shopping,
            title: 'Myeongdong Street Market',
            description: 'Cosmetics, street food, and shopping until dark.',
            imageAsset: 'assets/images/thumb-market.png',
          ),
        ],
      ),
      TripDay(
        dayNumber: 4,
        date: 'Oct 15',
        areaName: 'Dongdaemun Area',
        activities: [
          const TripActivity(
            id: 'd4-1',
            time: '10:30 AM',
            category: ActivityCategory.shopping,
            title: 'Dongdaemun Design Plaza',
            description: 'Futuristic architecture and design exhibitions.',
            imageAsset: 'assets/images/thumb-craft-stamp.png',
          ),
          const TripActivity(
            id: 'd4-2',
            time: '07:00 PM',
            category: ActivityCategory.shopping,
            title: 'Dongdaemun Night Market',
            description: 'Late-night shopping across multi-level fashion malls.',
            imageAsset: 'assets/images/thumb-market.png',
          ),
        ],
      ),
      TripDay(
        dayNumber: 5,
        date: 'Oct 16',
        areaName: 'Yeouido Area',
        activities: [
          const TripActivity(
            id: 'd5-1',
            time: '09:00 AM',
            category: ActivityCategory.nature,
            title: 'Yeouido Han River Park',
            description: 'A relaxed morning bike ride along the river.',
            imageAsset: 'assets/images/map-seoul.png',
          ),
          const TripActivity(
            id: 'd5-2',
            time: '01:00 PM',
            category: ActivityCategory.culture,
            title: 'Yeouido Hangang Park Picnic',
            description: 'Farewell picnic with skyline views before departure.',
            imageAsset: 'assets/images/thumb-food-vegan.png',
          ),
        ],
      ),
    ];
  }

  List<RouteStop> _buildRouteStops() {
    return const [
      RouteStop(
        order: 1,
        nameEn: 'Hongik University Area',
        nameKo: '홍익대학교',
        arrivalTime: '1:30 PM',
        transitMode: 'Subway (18m)',
        transitDetail: 'Subway Line 2 · 18 min · ₩1,400 · 420m walk',
        exitInstruction: 'Get off: Exit 9',
      ),
      RouteStop(
        order: 2,
        nameEn: 'Mangwon Market',
        nameKo: '망원시장',
        arrivalTime: '2:59 PM',
      ),
    ];
  }
}
