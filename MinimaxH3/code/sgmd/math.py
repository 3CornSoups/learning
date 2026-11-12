import torch
import torch.nn.functional as F


def expand_sigma(sigma, ndim):
    """Expand a batch sigma vector across non-batch tensor dimensions."""
    if sigma.ndim == 0:
        sigma = sigma.reshape(1)
    return sigma.reshape(
        sigma.shape[0],
        *([1] * (ndim - 1)),
    )


def euler_step(sample, velocity, sigma, sigma_next):
    """Advance a flow sample between two arbitrary sigma values."""
    sigma = expand_sigma(sigma, sample.ndim)
    sigma_next = expand_sigma(sigma_next, sample.ndim)
    return (sample + (sigma_next - sigma) * velocity).to(sample.dtype)


def velocity_to_x0(sample, velocity, sigma):
    """Project a flow velocity prediction from sigma to zero."""
    return euler_step(
        sample,
        velocity,
        sigma,
        torch.zeros_like(sigma),
    )


def do_cfg(cond_pred, uncond_pred, cfg_scale, cfg_norm):
    """Apply classifier-free guidance with the configured normalization."""
    pred = uncond_pred + cfg_scale * (cond_pred - uncond_pred)
    if cfg_norm in (None, "none"):
        return pred
    if cfg_norm == "layer_norm":
        cond_norm = torch.norm(cond_pred, dim=-1, keepdim=True)
        pred_norm = torch.norm(pred, dim=-1, keepdim=True)
        return pred * (cond_norm / torch.clamp(pred_norm, min=1e-12))
    if cfg_norm == "scalar":
        cond_norm = torch.norm(cond_pred)
        pred_norm = torch.norm(pred)
        return pred * min(
            1.0,
            (cond_norm / torch.clamp(pred_norm, min=1e-12)).item(),
        )
    raise ValueError(f"Unsupported cfg_norm: {cfg_norm}")


def dmd_loss(
    latents,
    x_pred_fake_flow,
    x_pred_teacher,
    norm_clip_min=None,
):
    """Compute the detached DMD regression objective."""
    with torch.no_grad():
        grad = x_pred_fake_flow - x_pred_teacher
        dims = tuple(range(1, latents.ndim))
        normalizer = torch.abs(latents - x_pred_teacher).mean(dim=dims, keepdim=True)
        if norm_clip_min is not None:
            normalizer = normalizer.clamp(min=float(norm_clip_min))
        grad = torch.nan_to_num(grad / normalizer)
    return 0.5 * F.mse_loss(
        latents.float(),
        (latents.float() - grad.float()).detach(),
        reduction="mean",
    )


def dmd_loss_pair(
    latents,
    x_pred_fake_flow,
    x_pred_teacher,
    video_weight,
    audio_weight,
):
    video_loss = dmd_loss(
        latents[0],
        x_pred_fake_flow[0],
        x_pred_teacher[0],
    )
    audio_loss = dmd_loss(
        latents[1],
        x_pred_fake_flow[1],
        x_pred_teacher[1],
    )
    return video_weight * video_loss + audio_weight * audio_loss


def normalized_fisher_loss(
    generated,
    x_pred_fake,
    x_pred_teacher,
):
    """Teacher-stop-gradient Fisher loss and a per-sample normalizer."""
    reduce_dims = tuple(range(1, generated.ndim))
    with torch.no_grad():
        normalizer = (generated.float() - x_pred_teacher.float()).abs().mean(
            dim=reduce_dims,
            keepdim=True,
        )
    per_element = 0.5 * (x_pred_fake.float() - x_pred_teacher.float()).square() / (normalizer + 1e-8)
    return per_element.flatten(1).mean(dim=1).mean(), normalizer


def normalized_fisher_loss_pair(
    generated,
    x_pred_fake,
    x_pred_teacher,
    video_weight,
    audio_weight,
):
    """Apply teacher-stop-gradient Fisher matching to H3 video and audio tokens."""
    video_loss, video_normalizer = normalized_fisher_loss(
        generated[0],
        x_pred_fake[0],
        x_pred_teacher[0],
    )
    audio_loss, audio_normalizer = normalized_fisher_loss(
        generated[1],
        x_pred_fake[1],
        x_pred_teacher[1],
    )
    return (
        video_weight * video_loss + audio_weight * audio_loss,
        (video_normalizer, audio_normalizer),
    )


def teacher_stop_gradient_fisher_loss_pair(
    x_pred_fake,
    x_pred_teacher,
    sigmas,
    video_weight,
    audio_weight,
):
    """Paper Eq. 13 for H3's xt=(1-sigma)x0+sigma*epsilon parameterization."""
    def _loss(fake, teacher, sigma):
        sigma = sigma.float().clamp_min(1e-8)
        alpha = 1.0 - sigma
        coefficient = alpha.square() / sigma.pow(4)
        return 0.5 * coefficient * (fake.float() - teacher.detach().float()).square().mean()

    video_loss = _loss(x_pred_fake[0], x_pred_teacher[0], sigmas[0])
    audio_loss = _loss(x_pred_fake[1], x_pred_teacher[1], sigmas[1])
    return video_weight * video_loss + audio_weight * audio_loss


def negative_residual_loss_pair(
    generated,
    x_pred_fake,
    video_weight,
    audio_weight,
):
    """Paper Eq. 18 NR term; fake prediction remains differentiable to input."""
    video_loss = -0.5 * F.mse_loss(
        x_pred_fake[0].float(),
        generated[0].detach().float(),
        reduction="mean",
    )
    audio_loss = -0.5 * F.mse_loss(
        x_pred_fake[1].float(),
        generated[1].detach().float(),
        reduction="mean",
    )
    return video_weight * video_loss + audio_weight * audio_loss


def generator_fake_correction_loss(
    generated,
    x_pred_fake,
    sigma,
):
    """Negative-residual correction for a single H3 latent modality."""
    expanded_sigma = expand_sigma(sigma.float(), x_pred_fake.ndim).clamp_min(1e-8)
    with torch.no_grad():
        correction = (x_pred_fake.float() - generated.detach().float()) / expanded_sigma
        pseudo_target = x_pred_fake.float() - correction
    return 0.5 * F.mse_loss(
        x_pred_fake.float(),
        pseudo_target,
        reduction="mean",
    )


def generator_fake_correction_loss_pair(
    generated,
    x_pred_fake,
    sigmas,
    video_weight,
    audio_weight,
):
    """Apply SGMD negative-residual correction to H3 video and audio tokens."""
    video_loss = generator_fake_correction_loss(generated[0], x_pred_fake[0], sigmas[0])
    audio_loss = generator_fake_correction_loss(generated[1], x_pred_fake[1], sigmas[1])
    return video_weight * video_loss + audio_weight * audio_loss


def normalized_x_pred_loss_pair(
    generated,
    x_pred_fake,
    normalizers,
    video_weight,
    audio_weight,
):
    """Detached residual-contraction diagnostic for the fake-score update."""
    video_loss = (
        0.5
        * (x_pred_fake[0].float() - generated[0].float()).square()
        / (normalizers[0].float() + 1e-8)
    ).mean()
    audio_loss = (
        0.5
        * (x_pred_fake[1].float() - generated[1].float()).square()
        / (normalizers[1].float() + 1e-8)
    ).mean()
    return video_weight * video_loss + audio_weight * audio_loss


def residual_contraction_loss_pair(
    generated,
    x_pred_fake,
    video_weight,
    audio_weight,
):
    """Paper Eq. 18 RC term with generator outputs treated as constants."""
    video_loss = 0.5 * F.mse_loss(
        x_pred_fake[0].float(),
        generated[0].detach().float(),
        reduction="mean",
    )
    audio_loss = 0.5 * F.mse_loss(
        x_pred_fake[1].float(),
        generated[1].detach().float(),
        reduction="mean",
    )
    return video_weight * video_loss + audio_weight * audio_loss


def weighted_mse_pair(
    pred,
    target,
    video_weight,
    audio_weight,
):
    video_loss = F.mse_loss(
        pred[0].float(),
        target[0].float(),
        reduction="mean",
    )
    audio_loss = F.mse_loss(
        pred[1].float(),
        target[1].float(),
        reduction="mean",
    )
    return video_weight * video_loss + audio_weight * audio_loss


def detach_pair(value):
    return value[0].detach(), value[1].detach()


def to_dtype_pair(value, dtype):
    return value[0].to(dtype=dtype), value[1].to(dtype=dtype)
