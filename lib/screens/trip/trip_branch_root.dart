import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/trip_provider.dart';
import 'final_route_screen.dart';
import 'stamp_book_optin_screen.dart';
import 'trip_empty_state_screen.dart';
import 'trip_reset_confirm_sheet.dart';

/// The Trip branch's root page: shows Trip_Empty-State when there's no
/// itinerary yet, a one-time Stamp Book opt-in right after a fresh
/// itinerary is generated, and Final Route (with persistent bottom nav)
/// once the trip is underway.
class TripBranchRoot extends StatefulWidget {
  const TripBranchRoot({
    super.key,
    required this.onStartPlanning,
    required this.onCheckInToday,
  });

  final VoidCallback onStartPlanning;
  final VoidCallback onCheckInToday;

  @override
  State<TripBranchRoot> createState() => _TripBranchRootState();
}

class _TripBranchRootState extends State<TripBranchRoot> {
  bool _stampOptInDecided = false;

  @override
  void initState() {
    super.initState();
    context.read<TripProvider>().loadCurrentTrip();
  }

  @override
  Widget build(BuildContext context) {
    final trip = context.watch<TripProvider>();

    if (trip.loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (!trip.hasItinerary) {
      _stampOptInDecided = false;
      return TripEmptyStateScreen(onStartPlanning: widget.onStartPlanning);
    }

    if (!_stampOptInDecided) {
      return StampBookOptInScreen(
        onStartCollecting: (enabled) {
          trip.setStampCollectionEnabled(enabled);
          setState(() => _stampOptInDecided = true);
        },
        onSkip: () {
          trip.setStampCollectionEnabled(false);
          setState(() => _stampOptInDecided = true);
        },
      );
    }

    return Column(
      children: [
        Expanded(
          child: FinalRouteScreen(
            itinerary: trip.itinerary!,
            onResetItinerary: () async {
              final confirmed = await showTripResetConfirmSheet(context);
              if (confirmed == true) {
                trip.resetItinerary();
                widget.onStartPlanning();
              }
            },
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: TextButton(
              onPressed: widget.onCheckInToday,
              child: const Text("Check in for today's places →"),
            ),
          ),
        ),
      ],
    );
  }
}
