import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/data/repositories/events_repository.dart';
import 'package:seoulfit_ui/models/event.dart';
import 'package:seoulfit_ui/screens/events/event_detail_sheet.dart';
import 'package:seoulfit_ui/screens/events/events_screen.dart';

/// A live event carries everything POST /events now returns. Mock data has no
/// contentid, which is what keeps the mock grid inert.
const _live = SeoulEvent(
  title: 'Gangdong Prehistoric Culture Festival',
  contentId: '4088698',
  lat: 37.559,
  lng: 127.130,
  dateRange: 'Oct 02, 2026 - Oct 04, 2026',
  venue: '47 Olympic-ro, Gangdong-gu',
  category: 'Festivals',
  posterColors: [Color(0xFF10312B), Color(0xFF4F8A7A)],
  landingUrl: 'https://english.visitkorea.or.kr/enu/ATR/'
      'SI_EN_3_1_1_1.jsp?cid=4088698',
);

const _mock = SeoulEvent(
  title: 'Les Misérables',
  dateRange: 'Jun 5 - Aug 18',
  venue: 'Blue Square Shinhan Hall',
  category: 'Festivals',
  posterColors: [Color(0xFF3A2E28), Color(0xFF8B2E22)],
);

Widget _host(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('tapping an event card opens its detail sheet', (tester) async {
    // The cards used to launch an external browser straight to a 400 page.
    await tester.pumpWidget(_host(EventsScreen(repository: _OneEvent(_live))));
    await tester.pumpAndSettle();

    expect(find.byType(EventDetailSheet), findsNothing);

    // The grid sits below the header and chips, off the 800x600 test viewport.
    await tester.ensureVisible(find.text(_live.title));
    await tester.pumpAndSettle();
    await tester.tap(find.text(_live.title));
    await tester.pumpAndSettle();

    final sheet =
        tester.widget<EventDetailSheet>(find.byType(EventDetailSheet));
    expect(sheet.event.contentId, '4088698');
  });

  testWidgets('an event with nothing to open leaves its card inert',
      (tester) async {
    // Mock builds are shaped like this — no contentid, no landing URL. There
    // is nothing behind the card, so tapping must not open an empty sheet.
    await tester.pumpWidget(_host(EventsScreen(repository: _OneEvent(_mock))));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text(_mock.title));
    await tester.pumpAndSettle();

    final card = tester.widget<GestureDetector>(
      find
          .ancestor(
            of: find.text(_mock.title),
            matching: find.byType(GestureDetector),
          )
          .first,
    );
    expect(card.onTap, isNull, reason: 'no contentid and no landing URL');
  });

  testWidgets('the sheet paints the card facts before any fetch resolves',
      (tester) async {
    // No ApiService in the tree — the fetch is skipped entirely. The title,
    // date and venue still have to be there, because a sheet that shows only
    // a spinner is worse than the card it replaced.
    await tester.pumpWidget(_host(const EventDetailSheet(event: _live)));
    await tester.pumpAndSettle();

    expect(find.text(_live.title), findsOneWidget);
    expect(find.text(_live.dateRange), findsOneWidget);
    expect(find.text(_live.venue), findsOneWidget);
  });

  testWidgets('fields TourAPI left empty are dropped, not shown blank',
      (tester) async {
    // Coverage is uneven upstream — venue lands on nearly every event, the
    // description on about half. A column of "not available" rows would be
    // worse than a short sheet, so empty facts render nothing at all.
    await tester.pumpWidget(_host(const EventDetailSheet(event: _live)));
    await tester.pumpAndSettle();

    expect(find.text('Hours'), findsNothing);
    expect(find.text('Admission'), findsNothing);
    expect(find.text('Venue'), findsOneWidget, reason: 'falls back to the card');
    expect(find.textContaining('No description published'), findsOneWidget);
  });

  testWidgets('an event with no coordinates hides the map button',
      (tester) async {
    const noCoords = SeoulEvent(
      title: 'Somewhere',
      contentId: '1',
      dateRange: '',
      venue: 'Unknown',
      category: 'Festivals',
      posterColors: [Color(0xFF000000), Color(0xFF111111)],
    );
    await tester.pumpWidget(_host(const EventDetailSheet(event: noCoords)));
    await tester.pumpAndSettle();

    expect(find.text('Open in Kakao Map'), findsNothing);
    expect(find.text('View on VisitKorea'), findsNothing, reason: 'no landing URL');
  });
}

class _OneEvent implements EventsRepository {
  const _OneEvent(this.event);

  final SeoulEvent event;

  @override
  Future<List<SeoulEvent>> fetchEvents(String category) async => [event];
}
