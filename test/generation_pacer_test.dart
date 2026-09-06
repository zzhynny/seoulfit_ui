import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/widgets/generation_pacer.dart';
import 'package:seoulfit_ui/widgets/loading_log_panel.dart';

void main() {
  Widget host({
    required Future<void> Function() run,
    required VoidCallback onComplete,
    required VoidCallback onFailed,
    Duration estimate = const Duration(seconds: 10),
    void Function(double, List<LoadingLogStep>)? capture,
  }) =>
      MaterialApp(
        home: Scaffold(
          body: GenerationPacer(
            stages: const ['one', 'two', 'three', 'four'],
            estimate: estimate,
            run: run,
            onComplete: onComplete,
            onFailed: onFailed,
            builder: (context, progress, steps) {
              capture?.call(progress, steps);
              return Text('${(progress * 100).round()}');
            },
          ),
        ),
      );

  testWidgets('never reaches 100% while the call is still running',
      (tester) async {
    // The backend reports no progress, so the bar is an estimate. Showing
    // 100% before the response lands would claim work that has not happened.
    final gate = Completer<void>();
    await tester.pumpWidget(host(
      run: () => gate.future,
      onComplete: () {},
      onFailed: () {},
      estimate: const Duration(seconds: 2),
    ));

    // Well past the estimate.
    await tester.pump(const Duration(seconds: 30));
    expect(find.text('95'), findsOneWidget);
    expect(find.text('100'), findsNothing);

    gate.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  });

  testWidgets('does not finish before the call does', (tester) async {
    // The old screen fired on a fixed 1.8s timer and then sat at its end
    // state for the remaining ~70s.
    final gate = Completer<void>();
    var completed = false;
    await tester.pumpWidget(host(
      run: () => gate.future,
      onComplete: () => completed = true,
      onFailed: () {},
      estimate: const Duration(milliseconds: 200),
    ));

    await tester.pump(const Duration(seconds: 5));
    expect(completed, isFalse);

    gate.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(completed, isTrue);
  });

  testWidgets('routes a thrown call to onFailed, not onComplete',
      (tester) async {
    var completed = false;
    var failed = false;
    await tester.pumpWidget(host(
      run: () async => throw Exception('backend down'),
      onComplete: () => completed = true,
      onFailed: () => failed = true,
    ));
    await tester.pump();

    expect(failed, isTrue);
    expect(completed, isFalse);
  });

  testWidgets('keeps the last stage active past the estimate', (tester) async {
    // Running long is normal — the call is allowed 180s. A finished-looking
    // checklist while it is still working would read as a hang.
    final gate = Completer<void>();
    late List<LoadingLogStep> steps;
    await tester.pumpWidget(host(
      run: () => gate.future,
      onComplete: () {},
      onFailed: () {},
      estimate: const Duration(seconds: 1),
      capture: (_, s) => steps = s,
    ));

    await tester.pump(const Duration(seconds: 20));
    expect(steps.last.state, LoadingLogStepState.active);
    expect(steps.where((s) => s.state == LoadingLogStepState.pending), isEmpty);

    gate.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  });
}
