import numpy as np
import pytest
import torch
from torch import nn
from vision.building_dino import LowRankLinear, DinoBuilding, inject_lora, merge_lora
from vision.building_learning import instance_targets, instance_loss, teacher_targets, group_balanced_order


def test_real_instance_targets_weight_and_shared_wall():
    ids=np.zeros((32,32),np.int32)
    ids[2:20,2:14]=10;ids[2:20,14:24]=99;ids[24:27,24:27]=1000
    y=instance_targets(ids>0,ids)
    assert y.shape==(5,32,32)
    assert y[4,5,13]==y[4,5,14]==1
    assert y[4,2,2]==0 and y[3,25,25]>y[3,5,5]
    x=torch.zeros((1,3,32,32),requires_grad=True)
    loss=instance_loss(x,torch.from_numpy(y[None]))
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(x.grad).all()
    assert (x.grad.abs().sum((0,2,3))>0).all()


def test_teacher_gates_wrong_labels_and_group_sampler():
    p=np.full((4,4),.9,np.float32);valid=np.ones_like(p,bool)
    a={"valid":valid,"probability":p};b={"valid":valid,"probability":1-p}
    t=teacher_targets(a,b)
    np.testing.assert_allclose(t[0],.5)
    y=torch.from_numpy(instance_targets(np.zeros((4,4),np.uint8),np.zeros((4,4),np.int32))[None])
    x=torch.zeros((1,3,4,4))
    wrong=torch.tensor(np.stack([p,np.ones_like(p)])[None])
    torch.testing.assert_close(instance_loss(x,y,wrong),instance_loss(x,y))
    groups=["a"]*20+["b"]
    order=group_balanced_order(groups,np.ones(21),np.random.default_rng(7),20)
    assert sum(groups[i]=="b" for i in order)==10


def test_lora_zero_init_and_merged_parity():
    torch.manual_seed(7)
    base=nn.Linear(12,8);x=torch.randn(4,12);expected=base(x).detach()
    adapter=LowRankLinear(base,4)
    torch.testing.assert_close(adapter(x),expected)
    with torch.no_grad():
        adapter.b.normal_(std=.1)
    y=adapter(x).detach()
    torch.testing.assert_close(adapter.merged()(x),y,atol=1e-6,rtol=1e-6)


def test_real_tiny_dinov3_pyramid_and_lora_gradient():
    from transformers import DINOv3ViTConfig,DINOv3ViTModel
    torch.set_num_threads(2)
    config=DINOv3ViTConfig(hidden_size=32,intermediate_size=64,num_hidden_layers=4,
        num_attention_heads=4,patch_size=16,image_size=64,num_register_tokens=2,
        attn_implementation="eager")
    encoder=DINOv3ViTModel(config).eval().requires_grad_(False)
    network=DinoBuilding(encoder,width=32).eval()
    names=inject_lora(encoder,4)
    assert names
    x=torch.randn(1,3,64,64)
    y=network(x)
    assert y.shape==(1,3,64,64)
    y.square().mean().backward()
    adapters=[m for m in network.modules() if isinstance(m,LowRankLinear)]
    assert all(m.base.weight.grad is None and m.b.grad is not None for m in adapters)
    expected=network(x).detach()
    merge_lora(network)
    torch.testing.assert_close(network(x),expected,atol=1e-5,rtol=1e-5)
