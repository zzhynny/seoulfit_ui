import 'package:flutter_test/flutter_test.dart';

import 'package:seoulfit_ui/main.dart';

void main() {
  testWidgets('App boots to the Splash screen', (WidgetTester tester) async {
    await tester.pumpWidget(const SeoulFitApp());
    await tester.pump();

    expect(find.text('SeoulFit'), findsOneWidget);
    expect(find.text('Get Started'), findsOneWidget);
  });
}
