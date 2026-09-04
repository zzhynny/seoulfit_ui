import 'package:flutter/material.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

/// Shows the Trip_Reset-Confirm bottom sheet. Resolves true if the user
/// chose "Yes, Start Over".
Future<bool?> showTripResetConfirmSheet(BuildContext context) {
  return showModalBottomSheet<bool>(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (context) => const _TripResetConfirmSheet(),
  );
}

class _TripResetConfirmSheet extends StatelessWidget {
  const _TripResetConfirmSheet();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.only(topLeft: Radius.circular(24), topRight: Radius.circular(24)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 40,
            height: 4,
            margin: const EdgeInsets.only(bottom: 16),
            decoration: BoxDecoration(color: const Color(0xFFD0D0D0), borderRadius: BorderRadius.circular(100)),
          ),
          Text('Start a New Journey?', style: AppTextStyles.headingSmall.copyWith(fontSize: 20, color: const Color(0xFF2D2A26))),
          const SizedBox(height: 12),
          Text(
            'Your current itinerary will be cleared. Are you sure you want to start over with AI?',
            textAlign: TextAlign.center,
            style: AppTextStyles.bodyMedium.copyWith(color: const Color(0xFF666666)),
          ),
          const SizedBox(height: 16),
          PrimaryButton(label: 'Yes, Start Over', onPressed: () => Navigator.of(context).pop(true)),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              style: TextButton.styleFrom(
                backgroundColor: const Color(0xFFF0F2F0),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: Text('Keep Current Plan', style: AppTextStyles.bodyLarge.copyWith(color: const Color(0xFF333333), fontWeight: FontWeight.w600)),
            ),
          ),
        ],
      ),
    );
  }
}
