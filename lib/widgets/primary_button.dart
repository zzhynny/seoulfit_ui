import 'package:flutter/material.dart';
import '../theme/theme.dart';

class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.enabled = true,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,
      width: double.infinity,
      child: ElevatedButton(
        onPressed: enabled ? onPressed : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          disabledBackgroundColor: AppColors.primary.withValues(alpha: 0.4),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.lg),
          ),
          elevation: 0,
        ),
        child: Text(label, style: AppTextStyles.buttonLabel),
      ),
    );
  }
}

class SecondaryTextButton extends StatelessWidget {
  const SecondaryTextButton({super.key, required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      onPressed: onPressed,
      child: Text(
        label,
        style: AppTextStyles.bodyMedium.copyWith(
          color: AppColors.textSecondary,
          fontWeight: FontWeight.w600,
          decoration: TextDecoration.underline,
        ),
      ),
    );
  }
}
