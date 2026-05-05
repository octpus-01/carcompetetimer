import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from threading import Lock
from typing import Dict, List, Optional
import uuid

class Team:
    """队伍数据模型"""
    def __init__(self, team_id: str, name: str):
        self.team_id = team_id
        self.name = name
        self.created_at = datetime.now().isoformat()
        self.status = "idle"  # idle, running, paused, stopped
        self.start_time: Optional[float] = None
        self.pause_time: Optional[float] = None
        self.total_elapsed: float = 0.0
        # 修改：step_times 现在存储的是该步骤的独立耗时，而不是截止总时间
        self.step_times: Dict[int, Optional[float]] = {1: None, 2: None, 3: None}
        self.total_time: Optional[float] = None

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "team_id": self.team_id,
            "name": self.name,
            "created_at": self.created_at,
            "status": self.status,
            "total_elapsed": round(self.get_current_elapsed(), 3),
            # 分段耗时直接展示
            "step_times": {
                step: round(time, 3) if time is not None else None
                for step, time in self.step_times.items()
            },
            "total_time": round(self.total_time, 3) if self.total_time is not None else None
        }

    def get_current_elapsed(self) -> float:
        """获取当前累计总耗时（用于显示总计时器）"""
        if self.status == "stopped" and self.total_time is not None:
            return self.total_time
        current = self.total_elapsed
        if self.status == "running" and self.start_time is not None:
            current += (datetime.now().timestamp() - self.start_time)
        elif self.status == "paused" and self.pause_time is not None:
            current += (self.pause_time - (self.start_time or 0.0))
        return current

    def start_timing(self):
        """开始或恢复计时"""
        now = datetime.now().timestamp()
        if self.status == "idle":
            self.start_time = now
            self.status = "running"
        elif self.status == "paused" and self.pause_time is not None:
            elapsed_during_pause = self.pause_time - (self.start_time or 0.0)
            self.start_time = now - elapsed_during_pause
            self.pause_time = None
            self.status = "running"

    def pause_timing(self):
        """暂停计时"""
        if self.status == "running" and self.start_time is not None:
            now = datetime.now().timestamp()
            self.total_elapsed += (now - self.start_time)
            self.start_time = None
            self.pause_time = now
            self.status = "paused"

    def stop_timing(self):
        """停止计时并记录总时间"""
        if self.status == "running":
            self.pause_timing()
        self.status = "stopped"
        self.total_time = self.total_elapsed

    def record_step(self, step: int):
        """
        核心修正：记录指定步骤的独立耗时
        耗时 = 当前总耗时 - 上一步骤的总耗时
        """
        if step not in [1, 2, 3]:
            raise ValueError("步骤编号必须为1、2或3")
        if self.step_times[step] is not None:
            raise ValueError(f"步骤{step}已完成，不可重复记录")
        
        # 获取记录这一刻的总耗时
        current_total_time = self.get_current_elapsed()
        
        # 计算上一步的结束时间点（如果是步骤1，上一步结束时间为0）
        prev_step_end_time = 0.0
        if step > 1:
            # 遍历之前的步骤，累加它们的独立耗时，得到上一步结束的时间点
            for i in range(1, step):
                if self.step_times[i] is not None:
                    prev_step_end_time += self.step_times[i]
                else:
                    # 如果前序步骤没记录（防止异常），则以前序步骤的理论时间点为准
                    # 这里简化处理，假设必须按顺序记录，如果前序为None，则视为0或报错
                    # 实际比赛中通常要求按顺序，这里我们假设按顺序点击
                    pass
        
        # 该步骤的独立耗时 = 当前总时间 - 上一步结束的时间点
        step_duration = current_total_time - prev_step_end_time
        self.step_times[step] = max(0, step_duration) # 防止负数
        
        # 如果三个步骤都记录完毕，自动停止总计时
        if all(t is not None for t in self.step_times.values()) and self.status in ["running", "paused"]:
            self.stop_timing()

class TimingManager:
    """计时管理系统"""
    def __init__(self):
        self.teams: Dict[str, Team] = {}
        self._lock = Lock()

    def add_team(self, name: str) -> Team:
        with self._lock:
            team_id = str(uuid.uuid4())[:8]
            while team_id in self.teams:
                team_id = str(uuid.uuid4())[:8]
            team = Team(team_id, name)
            self.teams[team_id] = team
            return team

    def remove_team(self, team_id: str) -> bool:
        with self._lock:
            if team_id not in self.teams:
                return False
            del self.teams[team_id]
            return True

    def get_team(self, team_id: str) -> Optional[Team]:
        with self._lock:
            return self.teams.get(team_id)

    def get_all_teams(self) -> List[Team]:
        with self._lock:
            return list(self.teams.values())

    def start_team_timing(self, team_id: str) -> bool:
        with self._lock:
            team = self.teams.get(team_id)
            if not team or team.status in ["running", "stopped"]:
                return False
            team.start_timing()
            return True

    def pause_team_timing(self, team_id: str) -> bool:
        with self._lock:
            team = self.teams.get(team_id)
            if not team or team.status != "running":
                return False
            team.pause_timing()
            return True

    def stop_team_timing(self, team_id: str) -> bool:
        with self._lock:
            team = self.teams.get(team_id)
            if not team or team.status == "stopped":
                return False
            team.stop_timing()
            return True

    def record_step(self, team_id: str, step: int) -> bool:
        with self._lock:
            team = self.teams.get(team_id)
            if not team:
                return False
            try:
                team.record_step(step)
                return True
            except ValueError:
                return False

    def calculate_step_ranking(self, step: int) -> List[Dict]:
        """计算指定步骤的排位（按该步骤的独立耗时排序）"""
        with self._lock:
            teams_with_step = [
                team for team in self.teams.values()
                if team.step_times.get(step) is not None
            ]
            
            def get_step_time(team: Team) -> float:
                time_val = team.step_times.get(step)
                return time_val if time_val is not None else float('inf')
            
            sorted_teams = sorted(teams_with_step, key=get_step_time)
            
            return [
                {
                    "rank": i + 1,
                    "team_id": team.team_id,
                    "name": team.name,
                    "time": round(team.step_times[step], 3),
                    "status": team.status
                }
                for i, team in enumerate(sorted_teams)
            ]

    def calculate_total_ranking(self) -> List[Dict]:
        """计算总计时排位"""
        with self._lock:
            completed_teams = [
                team for team in self.teams.values()
                if team.total_time is not None
            ]
            
            def get_total_time(team: Team) -> float:
                return team.total_time if team.total_time is not None else float('inf')
            
            sorted_teams = sorted(completed_teams, key=get_total_time)
            
            return [
                {
                    "rank": i + 1,
                    "team_id": team.team_id,
                    "name": team.name,
                    "total_time": round(team.total_time, 3),
                    "step_times": {
                        step: round(time, 3) if time is not None else None
                        for step, time in team.step_times.items()
                    },
                    "status": team.status
                }
                for i, team in enumerate(sorted_teams)
            ]

    def reset_all_teams(self):
        with self._lock:
            for team in self.teams.values():
                team.status = "idle"
                team.start_time = None
                team.pause_time = None
                team.total_elapsed = 0.0
                team.step_times = {1: None, 2: None, 3: None}
                team.total_time = None

# 初始化应用
app = Flask(__name__)
CORS(app)
timing_manager = TimingManager()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/teams', methods=['POST'])
def create_team():
    try:
        data = request.get_json()
        if not data or 'name' not in data:
            return jsonify({"error": "缺少队伍名称"}), 400
        name = data['name'].strip()
        if not name:
            return jsonify({"error": "队伍名称不能为空"}), 400
        team = timing_manager.add_team(name)
        return jsonify({"message": "队伍添加成功", "team": team.to_dict()}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/teams', methods=['GET'])
def get_all_teams():
    teams = [team.to_dict() for team in timing_manager.get_all_teams()]
    return jsonify({"count": len(teams), "teams": teams}), 200

@app.route('/api/teams/status', methods=['GET'])
def get_teams_status():
    """获取所有队伍的实时状态"""
    try:
        teams = timing_manager.get_all_teams()
        status_dict = {}
        for team in teams:
            status_dict[team.team_id] = team.to_dict()
        return jsonify(status_dict), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/teams/<team_id>/start', methods=['POST'])
def start_timing(team_id):
    success = timing_manager.start_team_timing(team_id)
    if not success: return jsonify({"error": "无法开始"}), 400
    return jsonify({"message": "开始成功"}), 200

@app.route('/api/teams/<team_id>/pause', methods=['POST'])
def pause_timing(team_id):
    success = timing_manager.pause_team_timing(team_id)
    if not success: return jsonify({"error": "无法暂停"}), 400
    return jsonify({"message": "暂停成功"}), 200

@app.route('/api/teams/<team_id>/stop', methods=['POST'])
def stop_timing(team_id):
    success = timing_manager.stop_team_timing(team_id)
    if not success: return jsonify({"error": "无法停止"}), 400
    return jsonify({"message": "停止成功"}), 200

@app.route('/api/teams/<team_id>/record_step/<int:step_number>', methods=['POST'])
def record_step(team_id, step_number):
    if step_number not in [1, 2, 3]: return jsonify({"error": "无效步骤"}), 400
    success = timing_manager.record_step(team_id, step_number)
    if not success: return jsonify({"error": "记录失败"}), 400
    return jsonify({"message": "记录成功"}), 200

@app.route('/api/rankings/step/<int:step_number>', methods=['GET'])
def get_step_ranking(step_number):
    if step_number not in [1, 2, 3]: return jsonify({"error": "无效步骤"}), 400
    ranking = timing_manager.calculate_step_ranking(step_number)
    return jsonify({"step": step_number, "ranking": ranking}), 200

@app.route('/api/rankings/total', methods=['GET'])
def get_total_ranking():
    ranking = timing_manager.calculate_total_ranking()
    return jsonify({"ranking": ranking}), 200

@app.route('/api/reset', methods=['POST'])
def reset_all():
    timing_manager.reset_all_teams()
    return jsonify({"message": "重置成功"}), 200

def main():
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)

if __name__ == '__main__':
    main()