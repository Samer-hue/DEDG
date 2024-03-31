import torch
from torch import nn
from torch.nn import functional as F


class DGNN(nn.Module):
    def __init__(self, args):
        super(DGNN, self).__init__()
        self.args = args
        self.vars = nn.ParameterList()

        w = nn.Parameter(torch.ones(*[args.hid_dim, args.feat_dim]))  # [16, 128]
        torch.nn.init.kaiming_normal_(w)
        self.vars.append(w)
        self.vars.append(nn.Parameter(torch.zeros(args.hid_dim)))

        w = nn.Parameter(torch.ones(*[args.hid_dim, args.feat_dim]))
        torch.nn.init.kaiming_normal_(w)
        self.vars.append(w)
        self.vars.append(nn.Parameter(torch.zeros(args.hid_dim)))

        w = nn.Parameter(torch.ones(*[args.out_dim, args.hid_dim]))
        torch.nn.init.kaiming_normal_(w)
        self.vars.append(w)
        self.vars.append(nn.Parameter(torch.zeros(args.out_dim)))

        w = nn.Parameter(torch.ones(*[args.out_dim, args.hid_dim]))
        torch.nn.init.kaiming_normal_(w)
        self.vars.append(w)
        self.vars.append(nn.Parameter(torch.zeros(args.out_dim)))

        delta_1 = nn.Parameter(torch.ones(*[1]))
        self.vars.append(delta_1)
        delta_2 = nn.Parameter(torch.ones(*[1]))
        self.vars.append(delta_2)
        # 经过上述操作后总共有了10个参数，[16,128],[16],[16,128],[16]  [16,16],[16],[16,16],[16]  [1] [1]

    def forward(self, self_feat, one_hop_feat, two_hop_feat, e_time, his_time, his_his_time, neg=False):
        vars = self.vars

        x_s = F.linear(self_feat, vars[0], vars[1])  # [b, d]
        x_n_one = F.linear(one_hop_feat, vars[2], vars[3])
        # 已经用W和b加权过了
        if neg == False:
            dif_t = e_time.reshape(-1, 1) - his_time
            decay = -vars[8] * dif_t
            # 加参数后的时间差
            soft_decay = F.softmax(decay, dim=1).reshape(-1, self.args.hist_len, 1)
            weighted_feat = soft_decay * (x_n_one.reshape(-1, self.args.hist_len, self.args.hid_dim))
            x_n_one = torch.sum(weighted_feat, dim=1)
        else:
            dif_t = e_time.reshape(-1, 1, 1) - his_time
            decay = -vars[8] * dif_t
            soft_decay = F.softmax(decay, dim=2).reshape(-1, self.args.neg_size, self.args.hist_len, 1)
            weighted_feat = soft_decay * (
                x_n_one.reshape(-1, self.args.neg_size, self.args.hist_len, self.args.hid_dim))
            x_n_one = torch.sum(weighted_feat, dim=2)
            x_s = x_s.reshape(-1, self.args.neg_size, self.args.hid_dim)
        x_s = x_s + x_n_one
        x_s_one = torch.relu(x_s)
        # 公式4

        x_one_s = F.linear(one_hop_feat, vars[0], vars[1])
        # 指的是一阶邻居自身特征
        x_n_two = F.linear(two_hop_feat, vars[2], vars[3])
        # 二阶邻居特征
        # 第二层邻域信息，如果是这么复杂的操作，那说明在temporal graph上做gnn也许不可行？
        if neg == False:
            dif_t = his_time.reshape(-1, self.args.hist_len, 1) - his_his_time
            decay = -vars[8] * dif_t
            soft_decay = F.softmax(decay, dim=2).reshape(-1, self.args.hist_len, self.args.hist_len, 1)
            weighted_feat = soft_decay * (
                x_n_two.reshape(-1, self.args.hist_len, self.args.hist_len, self.args.hid_dim))
            x_n_two = torch.sum(weighted_feat, dim=2)
            x_one_s = x_one_s.reshape(-1, self.args.hist_len, self.args.hid_dim)
        else:
            dif_t = his_time.reshape(-1, self.args.neg_size, self.args.hist_len, 1) - his_his_time
            decay = -vars[8] * dif_t
            soft_decay = F.softmax(decay, dim=3).reshape(-1, self.args.neg_size, self.args.hist_len, self.args.hist_len,
                                                         1)
            weighted_feat = soft_decay * (
                x_n_two.reshape(-1, self.args.neg_size, self.args.hist_len, self.args.hist_len, self.args.hid_dim))
            x_n_two = torch.sum(weighted_feat, dim=3)
            x_one_s = x_one_s.reshape(-1, self.args.neg_size, self.args.hist_len, self.args.hid_dim)
        x_one_s = x_one_s + x_n_two
        x_one_s = torch.relu(x_one_s)
        # 相当于是对节点s的一阶邻居完成了同样对s的操作，即伪聚合，因为这些邻居节点之后自己还是要重新聚合
        # 所以用的W和b是一样的参数

        x_s_one_final = F.linear(x_s_one, vars[4], vars[5])
        if neg == False:
            dif_t = e_time.reshape(-1, 1) - his_time
            decay = -vars[8] * dif_t
            soft_decay = F.softmax(decay, dim=1).reshape(-1, self.args.hist_len, 1)
            weighted_feat = soft_decay * x_one_s
            x_n_one_final = torch.sum(weighted_feat, dim=1)
        else:
            dif_t = e_time.reshape(-1, 1, 1) - his_time
            decay = -vars[8] * dif_t
            soft_decay = F.softmax(decay, dim=2).reshape(-1, self.args.neg_size, self.args.hist_len, 1)
            weighted_feat = soft_decay * x_one_s
            x_n_one_final = torch.sum(weighted_feat, dim=2)
        x_n_one_final = F.linear(x_n_one_final, vars[6], vars[7])
        x_s_final = x_s_one_final + x_n_one_final
        # 这才是真正的第二层信息聚合

        return x_s_final

    def hawkes(self, s_self_feat, t_self_feat, s_one_hop_feat,
                                  t_one_hop_feat, e_time, s_his_time, t_his_time):
        vars = self.vars

        s_emb = F.linear(s_self_feat, vars[0], vars[1])  # [b, d]
        t_emb = F.linear(t_self_feat, vars[0], vars[1])
        s_h_emb = F.linear(s_one_hop_feat, vars[2], vars[3]).reshape(-1, self.args.hist_len, self.args.hist_len)
        t_h_emb = F.linear(t_one_hop_feat, vars[2], vars[3]).reshape(-1, self.args.hist_len, self.args.hist_len)
        base_i = (s_emb - t_emb).pow(2).sum(dim=-1, keepdim=True)
        # base_i = torch.sigmoid(-torch.log(base_sim)) + 1e-6  # [b,1]

        att_1 = torch.softmax((s_emb.unsqueeze(1) - s_h_emb).pow(2).sum(dim=-1, keepdim=False), dim=-1)
        incre_sim_1 = (s_emb.unsqueeze(1) - t_h_emb).pow(2).sum(dim=-1, keepdim=False)  # [b,h]
        time_dif_1 = torch.exp(-vars[9] * (e_time.reshape(-1, 1) - t_his_time))  # [b,h]
        incre_i_1 = (att_1 * incre_sim_1 * time_dif_1).mean(dim=-1, keepdim=True)
        # incre_i_1 = torch.sigmoid(-torch.log(att_1 * incre_sim_1 * time_dif_1).sum(dim=-1, keepdim=True)) + 1e-6  # [b,1]

        att_2 = torch.softmax((t_emb.unsqueeze(1) - t_h_emb).pow(2).sum(dim=-1, keepdim=False), dim=-1)
        incre_sim_2 = (t_emb.unsqueeze(1) - s_h_emb).pow(2).sum(dim=-1, keepdim=False)
        time_dif_2 = torch.exp(-vars[9] * (e_time.reshape(-1, 1) - s_his_time))
        incre_i_2 = (att_2 * incre_sim_2 * time_dif_2).mean(dim=-1, keepdim=True)
        # incre_i_2 = torch.sigmoid(-torch.log(incre_sim_2 * time_dif_2).sum(dim=-1, keepdim=True)) + 1e-6  # [b,1]

        hawkes_itensity = base_i + incre_i_1 + incre_i_2
        return hawkes_itensity

    def parameters(self):
        return self.vars
