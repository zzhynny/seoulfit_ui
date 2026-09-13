import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/services/api_service.dart';
import 'package:seoulfit_ui/widgets/journey_stamp.dart';

void main() {
  Finder asset(String name) => find.byWidgetPredicate(
        (w) => w is Image && w.image is AssetImage && (w.image as AssetImage).assetName == name,
      );
  Finder networkImage(String url) => find.byWidgetPredicate(
        (w) => w is Image && w.image is NetworkImage && (w.image as NetworkImage).url == url,
      );
  final loader = find.text('Creating your stamp…');
  final nativeCard = find.text('native railway card');
  final readyLayout = find.text('route list');
  const stampUrl = 'http://localhost:8000/static/stamps/trip-abc.png?v=42';

  Future<void> pumpWith(
    WidgetTester tester,
    Future<StampStatus> Function(String tripId) fetchStatus, {
    int maxPolls = 60,
  }) async {
    await tester.pumpWidget(MaterialApp(
      home: SingleChildScrollView(
        child: JourneyStamp(
          tripId: 'trip-abc',
          apiBase: 'http://localhost:8000',
          pollEvery: const Duration(seconds: 3),
          maxPolls: maxPolls,
          fetchStatus: fetchStatus,
          placeholder: const SizedBox(height: 300, child: Text('native railway card')),
          readyBuilder: (context, stamp) => Column(children: [stamp, const Text('route list')]),
        ),
      ),
    ));
    await tester.pump();
    await tester.pump();
  }

  Future<void> nextPoll(WidgetTester tester) async {
    await tester.pump(const Duration(seconds: 3));
    await tester.pump();
  }

  test('stampImageUrl points at the stamp file, versioned', () {
    expect(stampImageUrl('http://localhost:8000', 'trip-abc', 42), stampUrl);
  });

  testWidgets('loading logo over the native card while generating, then the whole stamp',
      (tester) async {
    final replies = <StampStatus>[
      (status: 'generating', version: null),
      (status: 'generating', version: null),
      (status: 'ready', version: 42),
    ];
    var i = 0;
    await pumpWith(tester, (_) async => replies[i++]);

    expect(loader, findsOneWidget);
    expect(asset(kAppLogoAsset), findsOneWidget);
    expect(nativeCard, findsOneWidget);

    await nextPoll(tester);
    expect(loader, findsOneWidget);

    await nextPoll(tester);
    expect(loader, findsNothing);
    expect(nativeCard, findsNothing);
    expect(readyLayout, findsOneWidget);
    expect(networkImage(stampUrl), findsOneWidget);

    // Not cropped: contain-fit, inside a box with the image's own shape.
    expect(tester.widget<Image>(networkImage(stampUrl)).fit, BoxFit.contain);
    final box = tester.widget<AspectRatio>(
      find.ancestor(of: networkImage(stampUrl), matching: find.byType(AspectRatio)).first,
    );
    expect(box.aspectRatio, kStampAspectRatio);
  });

  testWidgets('tells its parent the stamp link once it is ready', (tester) async {
    // The recap's Download button lives outside this widget and must only
    // appear once there's an actual image to save.
    final replies = <StampStatus>[
      (status: 'generating', version: null),
      (status: 'ready', version: 42),
    ];
    var i = 0;
    final ready = <String>[];
    await tester.pumpWidget(MaterialApp(
      home: SingleChildScrollView(
        child: JourneyStamp(
          tripId: 'trip-abc',
          apiBase: 'http://localhost:8000',
          pollEvery: const Duration(seconds: 3),
          fetchStatus: (_) async => replies[i++],
          onReady: ready.add,
          placeholder: const SizedBox(height: 300),
          readyBuilder: (context, stamp) => stamp,
        ),
      ),
    ));
    await tester.pump();
    await tester.pump();
    expect(ready, isEmpty);

    await nextPoll(tester);
    expect(ready, [stampUrl]);
  });

  testWidgets('no stamp requested: native card, no loader, no more polling',
      (tester) async {
    var calls = 0;
    await pumpWith(tester, (_) async {
      calls++;
      return (status: 'none', version: null);
    });
    await tester.pump(const Duration(seconds: 10));

    expect(calls, 1);
    expect(loader, findsNothing);
    expect(nativeCard, findsOneWidget);
  });

  testWidgets('an unreachable backend leaves the native card', (tester) async {
    await pumpWith(tester, (_) async => throw Exception('offline'));

    expect(loader, findsNothing);
    expect(nativeCard, findsOneWidget);
  });

  testWidgets('gives up on a generation that never finishes', (tester) async {
    await pumpWith(tester, (_) async => (status: 'generating', version: null), maxPolls: 2);
    expect(loader, findsOneWidget);

    for (var i = 0; i < 3; i++) {
      await nextPoll(tester);
    }

    expect(loader, findsNothing);
    expect(nativeCard, findsOneWidget);
  });
}
