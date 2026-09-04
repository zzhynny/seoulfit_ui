import 'package:flutter/material.dart';
import '../theme/theme.dart';

/// The 3-dot onboarding progress indicator (top-right of each screen).
class ProgressDots extends StatelessWidget {
  const ProgressDots({super.key, required this.step, this.total = 3});

  final int step; // 1-indexed
  final int total;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 1; i <= total; i++)
          Padding(
            padding: const EdgeInsets.only(left: 6),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              height: 6,
              width: i == step ? 32 : 8,
              decoration: BoxDecoration(
                color: i == step ? AppColors.primary : AppColors.border,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
          ),
      ],
    );
  }
}
