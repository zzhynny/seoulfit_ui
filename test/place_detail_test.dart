import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/screens/trip/place_detail_sheet.dart';
import 'package:seoulfit_ui/services/api_service.dart';

const _activity = TripActivity(
  id: 'Gyeongbokgung Palace',
  time: '9:00 AM',
  category: ActivityCategory.culture,
  title: 'Gyeongbokgung Palace',
  description: '161 Sajik-ro, Jongno-gu',
  lat: 37.5775,
  lng: 126.9769,
  poiType: 'history',
);

Widget host(Widget child, {ApiService? api}) => MaterialApp(
      home: Provider<ApiService?>.value(
        value: api,
        child: Scaffold(body: child),
      ),
    );

/// An ApiService that already holds this stop's text; real lookups are counted.
class _SavedTextApi extends ApiService {
  int lookups = 0;

  @override
  String? cachedPoiDetail(String name) => '• Hours: 9am–6pm';

  @override
  Future<String> fetchPoiDetail(String name, {String type = ''}) async {
    lookups++;
    return '';
  }
}

void main() {
  testWidgets('reopening a stop shows its saved text at once, no spinner',
      (tester) async {
    final api = _SavedTextApi();
    await tester.pumpWidget(host(const PlaceDetailSheet(activity: _activity), api: api));

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('• Hours: 9am–6pm'), findsOneWidget);
    expect(find.text("You've arrived when"), findsNothing);
    expect(api.lookups, 0);
  });

  testWidgets('renders the stop without a backend and stops loading',
      (tester) async {
    // The mock build provides a null ApiService. The sheet must settle into
    // its empty state rather than spinning forever.
    await tester.pumpWidget(host(const PlaceDetailSheet(activity: _activity)));
    await tester.pumpAndSettle();

    expect(find.text('Gyeongbokgung Palace'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text("You've arrived when"), findsNothing);
    expect(find.text('No visitor info for this stop yet.'), findsOneWidget);
  });

  testWidgets('offers a maps link, labelled as the search it actually is',
      (tester) async {
    // There is no location fix on the itinerary screens, so kakaoRoute would
    // build a by/{mode} URL with an empty origin and produce a dead link.
    await tester.pumpWidget(host(const PlaceDetailSheet(activity: _activity)));
    await tester.pumpAndSettle();

    expect(find.text('Open in Kakao Map'), findsOneWidget);
    expect(find.text('Directions in Kakao Map'), findsNothing);
  });

  test('the raw planner type survives onto the activity for POI lookups', () {
    // /poi-detail takes {name, type}; the coarse
    // ActivityCategory enum can't reconstruct 'history'.
    expect(_activity.poiType, 'history');
    expect(_activity.copyWith(visited: true).poiType, 'history');
  });
}
